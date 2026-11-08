# ruff: noqa: E501
"""Telegram bots: Invoices and a reminder go to linked tenants (DL-211).

Owner (8 Nov 2026, card "Build sending Invoices to tenants on Telegram?"): "Invoice + reminder".
Each issued Invoice goes through the Tenant bot to every tenant linked to its Lease, and one
reminder goes 3 days before the due date while the Invoice is not fully paid.

1. ``app.telegram_invoice_notices`` keeps what was queued: one row per Invoice, kind (the Invoice
   itself or the reminder) and Telegram account, with its outbox message. It is never changed, and
   it is what stops a second Invoice message or a second reminder.
2. When an Invoice is issued (any way: the Issue button, the billing run, a settlement), a
   deferred trigger queues the Invoice message for each live link of its Lease (an Invoice without
   a Lease: each live link of its Customer), in the language the tenant chose. It runs at commit,
   so the Invoice number and lines are final. A Telegram problem never stops an Invoice from being
   issued: it is reported as a warning and the Invoice is issued as usual. Drafts and void
   Invoices are never sent.
3. ``app.telegram_invoice_reminders`` (``telegram.operate``, run by the send job) queues the
   reminder for each Invoice that is Unpaid or Partly paid, due in 1 to 3 days, issued on an
   earlier day, from 08:00 Property time. A tenant who linked after the Invoice was issued gets the
   reminder too.
4. ``app.telegram_invoices_page`` (``telegram.read``) lists the Invoices issued in the last 45
   days with who got them, so staff see which tenants still need a paper copy.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270709_381"
down_revision: str | None = "20270708_380"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REMIND_DAYS = 3
PAGE_DAYS = 45

TABLES = """
    CREATE TABLE app.telegram_invoice_notices (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        invoice_id uuid NOT NULL REFERENCES app.invoices (id) ON DELETE RESTRICT,
        kind text NOT NULL CHECK (kind IN ('ISSUED', 'REMINDER')),
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        outbox_id uuid NOT NULL UNIQUE REFERENCES app.telegram_outbox (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CONSTRAINT telegram_invoice_notices_once UNIQUE (invoice_id, kind, telegram_user_id)
    );
    CREATE INDEX telegram_invoice_notices_property_idx
        ON app.telegram_invoice_notices (property_id, created_at DESC);

    CREATE TRIGGER telegram_invoice_notices_append_only BEFORE UPDATE OR DELETE
        ON app.telegram_invoice_notices FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_invoice_notices_no_truncate BEFORE TRUNCATE
        ON app.telegram_invoice_notices FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
"""

FUNCTIONS = f"""
    -- US dollars as the tenant reads them: $1,234.50.
    CREATE FUNCTION app.telegram_usd(p_cents bigint) RETURNS text
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT '$' || to_char(p_cents / 100.0, 'FM999,999,999,990.00')
    $$;

    -- What is still to pay on an Invoice, in cents.
    CREATE FUNCTION app.telegram_invoice_to_pay(p_invoice uuid) RETURNS bigint
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT GREATEST(COALESCE(sum(app.invoice_line_outstanding(line.id)), 0), 0)::bigint
        FROM app.invoice_lines AS line WHERE line.invoice_id = p_invoice
    $$;

    -- What an Invoice message says: the number, the Unit, each line, the total, what is still to
    -- pay and the due date. Only these fields reach the text (telegram_texts).
    CREATE FUNCTION app.telegram_invoice_details(p_invoice uuid) RETURNS jsonb
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT jsonb_build_object(
            'number', invoice.invoice_number,
            'unit', COALESCE(unit.unit_number, '-'),
            'list', COALESCE((SELECT string_agg('• ' || line.description || ': '
                    || app.telegram_usd(line.amount_usd_cents), E'\\n' ORDER BY line.line_sequence)
                FROM app.invoice_lines AS line WHERE line.invoice_id = invoice.id), ''),
            'total', app.telegram_usd(COALESCE((SELECT sum(line.amount_usd_cents)
                FROM app.invoice_lines AS line WHERE line.invoice_id = invoice.id), 0)::bigint),
            'to_pay', app.telegram_usd(app.telegram_invoice_to_pay(invoice.id)),
            'due', to_char(invoice.due_date, 'DD/MM/YYYY'))
        FROM app.invoices AS invoice
        LEFT JOIN app.leases AS lease ON lease.id = invoice.lease_id
        LEFT JOIN app.units AS unit ON unit.id = lease.unit_id
        WHERE invoice.id = p_invoice
    $$;

    -- Who gets an Invoice: each Telegram account with a live link to its Lease (an Invoice
    -- without a Lease: to its Customer), with the language last chosen in the Tenant bot.
    CREATE FUNCTION app.telegram_invoice_people(p_invoice uuid)
    RETURNS TABLE (property_id uuid, telegram_user_id bigint, language text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT person.property_id, person.telegram_user_id,
            COALESCE((SELECT choice.language FROM app.telegram_language_choices AS choice
                      WHERE choice.bot_code = 'TENANT'
                        AND choice.telegram_user_id = person.telegram_user_id
                      ORDER BY choice.chosen_at DESC LIMIT 1), 'km')
        FROM (
            SELECT DISTINCT ON (link.telegram_user_id) link.property_id, link.telegram_user_id
            FROM app.invoices AS invoice
            JOIN app.tenant_telegram_links AS link
              ON link.lease_id = invoice.lease_id
              OR (invoice.lease_id IS NULL AND link.customer_id = invoice.customer_id)
            WHERE invoice.id = p_invoice
              AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                              WHERE ending.link_id = link.id)
            ORDER BY link.telegram_user_id, link.linked_at DESC
        ) AS person
    $$;

    -- Queue the Invoice message or its reminder for each person who has not had it yet.
    CREATE FUNCTION app.telegram_queue_invoice(p_invoice uuid, p_kind text, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_status text;
        v_details jsonb;
        v_code text;
        v_person record;
        v_outbox uuid;
        v_count integer := 0;
    BEGIN
        IF p_kind NOT IN ('ISSUED', 'REMINDER') THEN
            RAISE EXCEPTION 'Unknown Invoice message' USING ERRCODE = '22023';
        END IF;
        SELECT invoice.status INTO v_status FROM app.invoices AS invoice WHERE invoice.id = p_invoice;
        IF v_status IS NULL OR v_status IN ('DRAFT', 'VOID')
           OR (p_kind = 'REMINDER' AND v_status NOT IN ('UNPAID', 'PARTIALLY_PAID')) THEN
            RETURN 0;
        END IF;
        v_details := app.telegram_invoice_details(p_invoice);
        v_code := CASE WHEN p_kind = 'REMINDER' THEN 'tenant.invoice_reminder'
            WHEN app.telegram_invoice_to_pay(p_invoice) = 0 THEN 'tenant.invoice_paid'
            ELSE 'tenant.invoice' END;
        FOR v_person IN SELECT * FROM app.telegram_invoice_people(p_invoice) AS person
            WHERE NOT EXISTS (SELECT 1 FROM app.telegram_invoice_notices AS notice
                              WHERE notice.invoice_id = p_invoice AND notice.kind = p_kind
                                AND notice.telegram_user_id = person.telegram_user_id)
        LOOP
            INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
                details, keyboard, created_by)
            VALUES (v_person.property_id, 'TENANT', v_person.telegram_user_id, v_code,
                v_person.language, v_details, NULL, p_actor)
            RETURNING id INTO v_outbox;
            INSERT INTO app.telegram_invoice_notices (property_id, invoice_id, kind,
                telegram_user_id, outbox_id)
            VALUES (v_person.property_id, p_invoice, p_kind, v_person.telegram_user_id, v_outbox);
            v_count := v_count + 1;
        END LOOP;
        RETURN v_count;
    END $$;

    -- An issued Invoice goes to its linked tenants, at commit, once.
    CREATE FUNCTION app.telegram_invoice_issued() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        IF NEW.issued_at IS NULL OR (TG_OP = 'UPDATE' AND OLD.issued_at IS NOT NULL) THEN
            RETURN NULL;
        END IF;
        BEGIN
            PERFORM app.telegram_queue_invoice(NEW.id, 'ISSUED', NEW.issued_by);
        EXCEPTION WHEN OTHERS THEN
            -- The Invoice is issued anyway; the staff give a paper copy (the Invoices page shows it).
            RAISE WARNING 'telegram_invoice_not_queued %', SQLSTATE;
        END;
        RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER invoices_telegram_notice AFTER INSERT OR UPDATE OF issued_at
        ON app.invoices DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION app.telegram_invoice_issued();

    -- The reminder, {REMIND_DAYS} days before the due date (owner 8 Nov 2026), run by the send job.
    CREATE FUNCTION app.telegram_invoice_reminders(p_property uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_zone text;
        v_today date;
        v_invoice uuid;
        v_count integer := 0;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT property.timezone_name INTO v_zone FROM app.properties AS property
        WHERE property.id = p_property;
        v_today := timezone(v_zone, statement_timestamp())::date;
        IF extract(hour FROM timezone(v_zone, statement_timestamp())) < 8 THEN
            RETURN 0;
        END IF;
        FOR v_invoice IN
            SELECT DISTINCT invoice.id
            FROM app.tenant_telegram_links AS link
            JOIN app.invoices AS invoice
              ON invoice.lease_id = link.lease_id
              OR (invoice.lease_id IS NULL AND invoice.customer_id = link.customer_id)
            WHERE link.property_id = p_property
              AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                              WHERE ending.link_id = link.id)
              AND invoice.status IN ('UNPAID', 'PARTIALLY_PAID')
              AND invoice.due_date BETWEEN v_today + 1 AND v_today + {REMIND_DAYS}
              AND timezone(v_zone, invoice.issued_at)::date < v_today
              AND NOT EXISTS (SELECT 1 FROM app.telegram_invoice_notices AS notice
                              WHERE notice.invoice_id = invoice.id AND notice.kind = 'REMINDER'
                                AND notice.telegram_user_id = link.telegram_user_id)
        LOOP
            v_count := v_count + app.telegram_queue_invoice(v_invoice, 'REMINDER', p_actor);
        END LOOP;
        RETURN v_count;
    END $$;

    -- The Invoices of the last {PAGE_DAYS} days and who got them on Telegram.
    CREATE FUNCTION app.telegram_invoices_page(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_rows jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.read', p_property);
        SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'id', invoice.id, 'number', invoice.invoice_number,
                'unit_number', unit.unit_number, 'customer', customer.legal_name,
                'status', invoice.status, 'issued_at', invoice.issued_at,
                'due_date', invoice.due_date,
                'to_pay_usd_cents', app.telegram_invoice_to_pay(invoice.id),
                'sent', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                        'telegram_user_id', notice.telegram_user_id,
                        'queued_at', notice.created_at,
                        'state', COALESCE(final.outcome, 'WAITING'),
                        'sent_at', final.attempted_at) ORDER BY notice.created_at)
                    FROM app.telegram_invoice_notices AS notice
                    LEFT JOIN app.telegram_outbox_attempts AS final
                      ON final.outbox_id = notice.outbox_id AND final.outcome IN ('SENT', 'GAVE_UP')
                    WHERE notice.invoice_id = invoice.id AND notice.kind = 'ISSUED'), '[]'::jsonb),
                'reminded_at', (SELECT min(notice.created_at) FROM app.telegram_invoice_notices AS notice
                    WHERE notice.invoice_id = invoice.id AND notice.kind = 'REMINDER'))
                ORDER BY invoice.issued_at DESC, invoice.invoice_number), '[]'::jsonb)
        INTO v_rows
        FROM app.invoices AS invoice
        JOIN app.customers AS customer ON customer.id = invoice.customer_id
        LEFT JOIN app.leases AS lease ON lease.id = invoice.lease_id
        LEFT JOIN app.units AS unit ON unit.id = lease.unit_id
        WHERE invoice.issued_at IS NOT NULL AND invoice.status <> 'VOID'
          AND invoice.issued_at >= statement_timestamp() - interval '{PAGE_DAYS} days'
          AND (unit.property_id = p_property
               OR EXISTS (SELECT 1 FROM app.telegram_invoice_notices AS notice
                          WHERE notice.invoice_id = invoice.id AND notice.property_id = p_property));
        RETURN jsonb_build_object('invoices', v_rows,
            'rules', jsonb_build_object('remind_days', {REMIND_DAYS}, 'days', {PAGE_DAYS}));
    END $$;
"""

RUNTIME = (
    "app.telegram_invoice_reminders(uuid, uuid)",
    "app.telegram_invoices_page(uuid, uuid)",
)
INTERNAL = (
    "app.telegram_usd(bigint)",
    "app.telegram_invoice_details(uuid)",
    "app.telegram_invoice_to_pay(uuid)",
    "app.telegram_invoice_people(uuid)",
    "app.telegram_queue_invoice(uuid, text, uuid)",
    "app.telegram_invoice_issued()",
)


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    for signature in RUNTIME + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Tenant bot Invoice migration is forward-only")
