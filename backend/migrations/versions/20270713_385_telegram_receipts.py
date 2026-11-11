# ruff: noqa: E501
"""Telegram bots: a Receipt goes to the people linked to the Lease or stay it paid (DL-215).

Owner (11 Nov 2026): CHETANA Residence support is the one bot for everything a tenant gets from
the office, and Receipts come first after the QR ("All three, in that order"). Who gets them is
the owner's card of 11 Nov 2026 (see DL-215).

1. ``app.telegram_receipt_notices`` keeps what was queued: one row per Receipt and Telegram
   account, with its outbox message. It is never changed, and it stops a second Receipt message.
2. Every Payment makes its Receipt (migration 40). The pull job (about once a minute) queues the
   Receipt message for Receipts of the last 3 days that someone linked has not had yet, so what
   the money paid (Invoices, late-payment charges and Security Deposits, saved with it) is final
   even where a command makes its checks immediate. It goes to each live link of the Lease the
   Payment names, of the Leases of the Invoices it paid, of the stays whose Invoice it paid, and of
   the payer, in the language each person chose. A person who links later (a guest who paid
   before the QR at check-in) gets the Receipts of the day before the link too. A reversed Payment
   is not sent.
3. The message says the Receipt number (the Payment's document number), the date, the amount
   received (riel also shows its US dollar value), the method, what it paid, and money not used
   yet. The labels are in the person's language.
4. ``app.telegram_receipts_page`` (``telegram.read``) lists the Receipts of the last 45 days with
   who got them, so staff see who still needs a paper copy.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270713_385"
down_revision: str | None = "20270712_384"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PAGE_DAYS = 45
# The owner's card of 11 Nov 2026: whether guests (links to a short stay) get Receipts.
GUESTS_GET_RECEIPTS = True
# Receipts newer than this are sent; a person gets those issued from a day before the link.
RECENT_DAYS = 3
LINK_DAYS_BACK = 1

TABLES = """
    CREATE TABLE app.telegram_receipt_notices (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        receipt_id uuid NOT NULL REFERENCES app.receipts (id) ON DELETE RESTRICT,
        telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
        outbox_id uuid NOT NULL UNIQUE REFERENCES app.telegram_outbox (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CONSTRAINT telegram_receipt_notices_once UNIQUE (receipt_id, telegram_user_id)
    );
    CREATE INDEX telegram_receipt_notices_property_idx
        ON app.telegram_receipt_notices (property_id, created_at DESC);

    CREATE TRIGGER telegram_receipt_notices_append_only BEFORE UPDATE OR DELETE
        ON app.telegram_receipt_notices FOR EACH ROW EXECUTE FUNCTION app.reject_telegram_change();
    CREATE TRIGGER telegram_receipt_notices_no_truncate BEFORE TRUNCATE
        ON app.telegram_receipt_notices FOR EACH STATEMENT EXECUTE FUNCTION app.reject_telegram_change();
    REVOKE ALL ON app.telegram_receipt_notices FROM PUBLIC;
"""

GUEST_FILTER = "" if GUESTS_GET_RECEIPTS else "AND link.booking_id IS NULL"

FUNCTIONS = f"""
    -- Riel as the tenant reads it: 410,000 ៛.
    CREATE FUNCTION app.telegram_khr(p_riel bigint) RETURNS text
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT to_char(p_riel, 'FM999,999,999,999,990') || ' ៛'
    $$;

    -- The Leases and stays a Receipt's Payment is for: the Lease it names, the Leases of the
    -- Invoices and late-payment charges it paid, and the stays whose Invoice it paid.
    CREATE FUNCTION app.telegram_receipt_people(p_receipt uuid)
    RETURNS TABLE (property_id uuid, telegram_user_id bigint, language text, linked_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        WITH payment AS (
            SELECT payment.* FROM app.receipts AS receipt
            JOIN app.payments AS payment ON payment.id = receipt.payment_id
            WHERE receipt.id = p_receipt
        ), paid AS (
            SELECT allocation.invoice_id AS invoice_id FROM app.payment_allocations AS allocation
            WHERE allocation.payment_id = (SELECT id FROM payment) AND allocation.invoice_id IS NOT NULL
            UNION
            SELECT charge.source_invoice_id FROM app.payment_allocations AS allocation
            JOIN app.late_payment_charges AS charge ON charge.id = allocation.late_payment_charge_id
            WHERE allocation.payment_id = (SELECT id FROM payment)
        ), leases AS (
            SELECT payment.lease_id FROM payment WHERE payment.lease_id IS NOT NULL
            UNION
            SELECT invoice.lease_id FROM app.invoices AS invoice
            WHERE invoice.id IN (SELECT invoice_id FROM paid) AND invoice.lease_id IS NOT NULL
            UNION
            SELECT deposit.lease_id FROM app.deposit_receipts AS taken
            JOIN app.deposits AS deposit ON deposit.id = taken.deposit_id
            WHERE taken.payment_id = (SELECT id FROM payment) AND deposit.lease_id IS NOT NULL
        ), stays AS (
            SELECT booking.id FROM app.short_stay_bookings AS booking
            WHERE booking.invoice_id IN (SELECT invoice_id FROM paid)
        )
        SELECT person.property_id, person.telegram_user_id,
            COALESCE((SELECT choice.language FROM app.telegram_language_choices AS choice
                      WHERE choice.bot_code = 'TENANT'
                        AND choice.telegram_user_id = person.telegram_user_id
                      ORDER BY choice.chosen_at DESC LIMIT 1), 'km'),
            person.linked_at
        FROM (
            SELECT DISTINCT ON (link.telegram_user_id) link.property_id, link.telegram_user_id,
                link.linked_at
            FROM app.tenant_telegram_links AS link
            WHERE link.property_id = (SELECT property_id FROM payment)
              AND (link.lease_id IN (SELECT lease_id FROM leases)
                   OR link.booking_id IN (SELECT id FROM stays)
                   OR link.customer_id = (SELECT payer_customer_id FROM payment))
              {GUEST_FILTER}
              AND NOT EXISTS (SELECT 1 FROM app.tenant_telegram_link_endings AS ending
                              WHERE ending.link_id = link.id)
              AND app.tenant_link_stay_live(link.lease_id, link.booking_id,
                                            app.gl_today(link.property_id))
            ORDER BY link.telegram_user_id, link.linked_at DESC
        ) AS person
    $$;

    -- The Receipt message's fields, with the labels in the person's language.
    CREATE FUNCTION app.telegram_receipt_details(p_receipt uuid, p_language text) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_km boolean := p_language = 'km';
        v_payment app.payments%ROWTYPE;
        v_unit text;
        v_lines text[];
        v_used bigint;
        v_amount text;
    BEGIN
        SELECT payment.* INTO v_payment FROM app.receipts AS receipt
        JOIN app.payments AS payment ON payment.id = receipt.payment_id
        WHERE receipt.id = p_receipt;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Unknown Receipt' USING ERRCODE = '22023';
        END IF;
        SELECT string_agg(DISTINCT unit.unit_number, ', ') INTO v_unit
        FROM app.units AS unit
        WHERE unit.id IN (
            SELECT lease.unit_id FROM app.leases AS lease WHERE lease.id = v_payment.lease_id
            UNION
            SELECT lease.unit_id FROM app.payment_allocations AS allocation
            LEFT JOIN app.late_payment_charges AS charge ON charge.id = allocation.late_payment_charge_id
            JOIN app.invoices AS invoice
              ON invoice.id = COALESCE(allocation.invoice_id, charge.source_invoice_id)
            JOIN app.leases AS lease ON lease.id = invoice.lease_id
            WHERE allocation.payment_id = v_payment.id
            UNION
            SELECT booking.unit_id FROM app.payment_allocations AS allocation
            JOIN app.short_stay_bookings AS booking ON booking.invoice_id = allocation.invoice_id
            WHERE allocation.payment_id = v_payment.id);
        SELECT array_agg(item.line ORDER BY item.position, item.number) INTO v_lines
        FROM (
            SELECT 1 AS position, invoice.invoice_number AS number,
                '• ' || CASE WHEN v_km THEN 'វិក្កយបត្រ ' ELSE 'Invoice ' END
                || invoice.invoice_number || ': ' || app.telegram_usd(sum(allocation.amount_usd_cents)::bigint) AS line
            FROM app.payment_allocations AS allocation
            JOIN app.invoices AS invoice ON invoice.id = allocation.invoice_id
            WHERE allocation.payment_id = v_payment.id AND allocation.target_kind = 'INVOICE'
            GROUP BY invoice.invoice_number
            UNION ALL
            SELECT 2, invoice.invoice_number,
                '• ' || CASE WHEN v_km THEN 'ប្រាក់ពិន័យបង់យឺត វិក្កយបត្រ ' ELSE 'Late payment charge, Invoice ' END
                || invoice.invoice_number || ': ' || app.telegram_usd(sum(allocation.amount_usd_cents)::bigint)
            FROM app.payment_allocations AS allocation
            JOIN app.late_payment_charges AS charge ON charge.id = allocation.late_payment_charge_id
            JOIN app.invoices AS invoice ON invoice.id = charge.source_invoice_id
            WHERE allocation.payment_id = v_payment.id AND allocation.target_kind = 'LATE_PAYMENT_CHARGE'
            GROUP BY invoice.invoice_number
            UNION ALL
            SELECT 3, '',
                '• ' || CASE WHEN v_km THEN 'ប្រាក់កក់ធានា' ELSE 'Security Deposit' END
                || ': ' || app.telegram_usd(sum(taken.amount_usd_cents)::bigint)
            FROM app.deposit_receipts AS taken
            WHERE taken.payment_id = v_payment.id
            HAVING count(*) > 0
        ) AS item;
        v_used := COALESCE((SELECT sum(allocation.amount_usd_cents) FROM app.payment_allocations AS allocation
                            WHERE allocation.payment_id = v_payment.id), 0)
                + COALESCE((SELECT sum(taken.amount_usd_cents) FROM app.deposit_receipts AS taken
                            WHERE taken.payment_id = v_payment.id), 0);
        IF v_payment.usd_accounting_value_cents > v_used THEN
            v_lines := COALESCE(v_lines, ARRAY[]::text[]) || ('• '
                || CASE WHEN v_km THEN 'មិនទាន់ប្រើ (រក្សាទុកសម្រាប់លើកក្រោយ)' ELSE 'Not used yet (kept for you)' END
                || ': ' || app.telegram_usd(v_payment.usd_accounting_value_cents - v_used));
        END IF;
        v_amount := CASE WHEN v_payment.received_currency = 'KHR'
            THEN app.telegram_khr(v_payment.received_amount_minor) || ' ('
                 || app.telegram_usd(v_payment.usd_accounting_value_cents) || ')'
            ELSE app.telegram_usd(v_payment.received_amount_minor) END;
        RETURN jsonb_build_object(
            'number', v_payment.payment_number,
            'unit', COALESCE(v_unit, '-'),
            'date', to_char(v_payment.payment_date, 'DD/MM/YYYY'),
            'amount', v_amount,
            'method', v_payment.payment_method_name_snapshot,
            'list', array_to_string(COALESCE(v_lines, ARRAY[]::text[]), E'\\n'));
    END $$;

    -- Queue the Receipt message for each person who has not had it yet.
    CREATE FUNCTION app.telegram_queue_receipt(p_receipt uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_issued timestamptz;
        v_person record;
        v_outbox uuid;
        v_count integer := 0;
    BEGIN
        SELECT receipt.issued_at INTO v_issued FROM app.receipts AS receipt
        JOIN app.payments AS payment ON payment.id = receipt.payment_id
        WHERE receipt.id = p_receipt AND payment.status = 'RECEIVED';
        IF v_issued IS NULL THEN
            RETURN 0;
        END IF;
        FOR v_person IN SELECT * FROM app.telegram_receipt_people(p_receipt) AS person
            WHERE person.linked_at - interval '{LINK_DAYS_BACK} day' <= v_issued
              AND NOT EXISTS (SELECT 1 FROM app.telegram_receipt_notices AS notice
                              WHERE notice.receipt_id = p_receipt
                                AND notice.telegram_user_id = person.telegram_user_id)
        LOOP
            INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language,
                details, keyboard, created_by)
            VALUES (v_person.property_id, 'TENANT', v_person.telegram_user_id, 'tenant.receipt',
                v_person.language, app.telegram_receipt_details(p_receipt, v_person.language),
                NULL, p_actor)
            RETURNING id INTO v_outbox;
            INSERT INTO app.telegram_receipt_notices (property_id, receipt_id, telegram_user_id,
                outbox_id)
            VALUES (v_person.property_id, p_receipt, v_person.telegram_user_id, v_outbox);
            v_count := v_count + 1;
        END LOOP;
        RETURN v_count;
    END $$;

    -- Run by the pull job: the Receipts of the last {RECENT_DAYS} days not yet sent to someone linked.
    CREATE FUNCTION app.telegram_receipts_queue(p_property uuid, p_actor uuid)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_receipt uuid;
        v_count integer := 0;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        FOR v_receipt IN
            SELECT receipt.id FROM app.receipts AS receipt
            JOIN app.payments AS payment ON payment.id = receipt.payment_id
            WHERE payment.property_id = p_property AND payment.status = 'RECEIVED'
              AND receipt.issued_at >= statement_timestamp() - interval '{RECENT_DAYS} days'
            ORDER BY receipt.issued_at, receipt.id
        LOOP
            v_count := v_count + app.telegram_queue_receipt(v_receipt, p_actor);
        END LOOP;
        RETURN v_count;
    END $$;

    -- The Receipts of the last {PAGE_DAYS} days and who got them on Telegram.
    CREATE FUNCTION app.telegram_receipts_page(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_rows jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.read', p_property);
        SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'id', receipt.id, 'number', payment.payment_number,
                'customer', customer.legal_name, 'status', payment.status,
                'issued_at', receipt.issued_at,
                'amount_usd_cents', payment.usd_accounting_value_cents,
                'sent', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                        'telegram_user_id', notice.telegram_user_id,
                        'queued_at', notice.created_at,
                        'state', COALESCE(final.outcome, 'WAITING'),
                        'sent_at', final.attempted_at) ORDER BY notice.created_at)
                    FROM app.telegram_receipt_notices AS notice
                    LEFT JOIN app.telegram_outbox_attempts AS final
                      ON final.outbox_id = notice.outbox_id AND final.outcome IN ('SENT', 'GAVE_UP')
                    WHERE notice.receipt_id = receipt.id), '[]'::jsonb))
                ORDER BY receipt.issued_at DESC, payment.payment_number), '[]'::jsonb)
        INTO v_rows
        FROM app.receipts AS receipt
        JOIN app.payments AS payment ON payment.id = receipt.payment_id
        JOIN app.customers AS customer ON customer.id = payment.payer_customer_id
        WHERE payment.property_id = p_property
          AND receipt.issued_at >= statement_timestamp() - interval '{PAGE_DAYS} days';
        RETURN jsonb_build_object('receipts', v_rows, 'rules', jsonb_build_object('days', {PAGE_DAYS}));
    END $$;
"""

RUNTIME = (
    "app.telegram_receipts_queue(uuid, uuid)",
    "app.telegram_receipts_page(uuid, uuid)",
)
INTERNAL = (
    "app.telegram_khr(bigint)",
    "app.telegram_receipt_people(uuid)",
    "app.telegram_receipt_details(uuid, text)",
    "app.telegram_queue_receipt(uuid, uuid)",
)


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    for signature in RUNTIME + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the Tenant bot Receipt migration is forward-only")
