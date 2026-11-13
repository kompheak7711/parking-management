# ruff: noqa: E501
"""ABA QR on every Invoice (owner 11 Nov 2026, cards "Approve the plan and the 5 money answers
for the ABA QR?" = "Yes, all recommended"; DL-180).

Each Invoice the Tenant bot sends goes as the A4 PDF of the approved Invoice sample, with an ABA
PayWay QR that already holds the amount to pay. These tables keep every QR asked from ABA and
what happened to it. Nothing is ever changed: a new state is a new event row.

1. ``app.aba_qr_requests``: one row per QR: the Invoice, our transaction id (unique, at most 20
   letters, the Invoice number and a count), the amount in cents (USD), the QR text and when it
   stops working (5 days after the Due Date, owner answer 3).
2. ``app.aba_qr_events``: CLOSED (a new QR replaced it, answer 1), PAID (ABA says paid),
   PAYMENT_RECORDED (the Payment is saved), NEEDS_CHECK (paid, but not as the QR asked: staff
   look, answer 4), EXPIRED, CHECK_FAILED (a check with ABA failed; tried again later).
3. ``app.aba_invoice_for_outbox`` gives the send job what the PDF needs for an Invoice message:
   the Invoice resource, the Customer's name and phone, the Unit, what is still to pay and the
   open QR of that amount if there is one.
4. ``app.aba_record_qr`` and ``app.aba_record_qr_event`` save a QR and its events;
   ``app.aba_qr_to_check`` lists the QRs to ask ABA about; ``app.aba_payment_method`` finds the
   Payment Method a QR payment is recorded with (operations file ``aba_payway``).

All functions need ``telegram.operate`` (the account the office jobs run as). Technical choices by
Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270717_340"
down_revision: str | None = "20270722_377"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = """
    CREATE TABLE app.aba_qr_requests (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        property_id uuid NOT NULL REFERENCES app.properties (id) ON DELETE RESTRICT,
        invoice_id uuid NOT NULL REFERENCES app.invoices (id) ON DELETE RESTRICT,
        tran_id text NOT NULL UNIQUE CHECK (tran_id ~ '^[A-Za-z0-9-]{1,20}$'),
        amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents > 0),
        currency text NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
        qr_string text NOT NULL CHECK (qr_string LIKE '000201%' AND length(qr_string) <= 1000),
        expires_at timestamptz NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.user_accounts (actor_id) ON DELETE RESTRICT,
        CHECK (expires_at > created_at)
    );
    CREATE INDEX aba_qr_requests_invoice_idx ON app.aba_qr_requests (invoice_id, created_at DESC);
    CREATE INDEX aba_qr_requests_property_idx ON app.aba_qr_requests (property_id, created_at DESC);

    CREATE TABLE app.aba_qr_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        request_id uuid NOT NULL REFERENCES app.aba_qr_requests (id) ON DELETE RESTRICT,
        kind text NOT NULL CHECK (kind IN ('CLOSED', 'PAID', 'PAYMENT_RECORDED', 'NEEDS_CHECK',
            'EXPIRED', 'CHECK_FAILED')),
        details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'
            AND length(details::text) <= 4000),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_by uuid NOT NULL REFERENCES app.user_accounts (actor_id) ON DELETE RESTRICT
    );
    CREATE INDEX aba_qr_events_request_idx ON app.aba_qr_events (request_id, created_at);
    -- One final word per QR: it is paid (or needs a look), closed or expired only once.
    CREATE UNIQUE INDEX aba_qr_events_once ON app.aba_qr_events (request_id, kind)
        WHERE kind IN ('CLOSED', 'PAID', 'PAYMENT_RECORDED', 'NEEDS_CHECK', 'EXPIRED');

    CREATE FUNCTION app.reject_aba_qr_change() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
        RAISE EXCEPTION 'ABA QR records are append-only' USING ERRCODE = '55000';
    END $$;
    REVOKE ALL ON FUNCTION app.reject_aba_qr_change() FROM PUBLIC;
    CREATE TRIGGER aba_qr_requests_append_only BEFORE UPDATE OR DELETE ON app.aba_qr_requests
        FOR EACH ROW EXECUTE FUNCTION app.reject_aba_qr_change();
    CREATE TRIGGER aba_qr_requests_no_truncate BEFORE TRUNCATE ON app.aba_qr_requests
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_aba_qr_change();
    CREATE TRIGGER aba_qr_events_append_only BEFORE UPDATE OR DELETE ON app.aba_qr_events
        FOR EACH ROW EXECUTE FUNCTION app.reject_aba_qr_change();
    CREATE TRIGGER aba_qr_events_no_truncate BEFORE TRUNCATE ON app.aba_qr_events
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_aba_qr_change();
"""

FUNCTIONS = """
    -- A QR is open while nothing final happened to it and it still works.
    CREATE FUNCTION app.aba_qr_open(p_request uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        SELECT EXISTS (SELECT 1 FROM app.aba_qr_requests AS request
                       WHERE request.id = p_request AND request.expires_at > statement_timestamp())
           AND NOT EXISTS (SELECT 1 FROM app.aba_qr_events AS event
                           WHERE event.request_id = p_request
                             AND event.kind IN ('CLOSED', 'PAID', 'PAYMENT_RECORDED',
                                                'NEEDS_CHECK', 'EXPIRED'))
    $$;

    -- What the send job needs to make the PDF of an Invoice message (NULL: not an Invoice message).
    CREATE FUNCTION app.aba_invoice_for_outbox(p_property uuid, p_outbox uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_invoice uuid;
        v_result jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT notice.invoice_id INTO v_invoice FROM app.telegram_invoice_notices AS notice
        WHERE notice.outbox_id = p_outbox AND notice.property_id = p_property;
        IF v_invoice IS NULL THEN
            RETURN NULL;
        END IF;
        SELECT jsonb_build_object(
            'invoice_id', invoice.id,
            'invoice', app.invoice_resource_snapshot(invoice.id),
            'customer_name', customer.legal_name,
            'customer_phone', customer.phone_number,
            'unit', unit.unit_number,
            'to_pay_usd_cents', app.telegram_invoice_to_pay(invoice.id),
            'due_date', invoice.due_date,
            'today', timezone(property.timezone_name, statement_timestamp())::date,
            'timezone', property.timezone_name,
            'qr_count', (SELECT count(*) FROM app.aba_qr_requests AS request
                         WHERE request.invoice_id = invoice.id),
            'open_qrs', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'tran_id', request.tran_id, 'amount_usd_cents', request.amount_usd_cents,
                    'qr_string', request.qr_string, 'expires_at', request.expires_at)
                    ORDER BY request.created_at DESC)
                FROM app.aba_qr_requests AS request
                WHERE request.invoice_id = invoice.id AND app.aba_qr_open(request.id)), '[]'::jsonb))
        INTO v_result
        FROM app.invoices AS invoice
        JOIN app.customers AS customer ON customer.id = invoice.customer_id
        JOIN app.properties AS property ON property.id = p_property
        LEFT JOIN app.leases AS lease ON lease.id = invoice.lease_id
        LEFT JOIN app.units AS unit ON unit.id = lease.unit_id
        WHERE invoice.id = v_invoice;
        RETURN v_result;
    END $$;

    -- Save a QR that ABA made for an Invoice.
    CREATE FUNCTION app.aba_record_qr(p_property uuid, p_invoice uuid, p_tran_id text,
        p_amount bigint, p_qr_string text, p_expires_at timestamptz, p_actor uuid)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_id uuid;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        IF NOT EXISTS (SELECT 1 FROM app.telegram_invoice_notices AS notice
                       WHERE notice.invoice_id = p_invoice AND notice.property_id = p_property) THEN
            RAISE EXCEPTION 'not an Invoice of this Property' USING ERRCODE = '22023';
        END IF;
        INSERT INTO app.aba_qr_requests (property_id, invoice_id, tran_id, amount_usd_cents,
            qr_string, expires_at, created_by)
        VALUES (p_property, p_invoice, p_tran_id, p_amount, p_qr_string, p_expires_at, p_actor)
        RETURNING id INTO v_id;
        RETURN v_id;
    END $$;

    -- Save what happened to a QR. A final word said twice is kept once (returns NULL).
    CREATE FUNCTION app.aba_record_qr_event(p_property uuid, p_tran_id text, p_kind text,
        p_details jsonb, p_actor uuid)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_request uuid;
        v_id uuid;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT request.id INTO v_request FROM app.aba_qr_requests AS request
        WHERE request.tran_id = p_tran_id AND request.property_id = p_property;
        IF v_request IS NULL THEN
            RAISE EXCEPTION 'unknown ABA transaction' USING ERRCODE = 'P0002';
        END IF;
        INSERT INTO app.aba_qr_events (request_id, kind, details, created_by)
        VALUES (v_request, p_kind, COALESCE(p_details, '{}'::jsonb), p_actor)
        ON CONFLICT DO NOTHING
        RETURNING id INTO v_id;
        RETURN v_id;
    END $$;

    -- The accepted Payment Method a QR payment is recorded with, by its code (NULL: none).
    CREATE FUNCTION app.aba_payment_method(p_property uuid, p_code text, p_actor uuid)
    RETURNS uuid LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        RETURN (SELECT method.id FROM app.payment_methods AS method
                WHERE method.code = p_code AND method.accepted);
    END $$;

    -- The QRs to ask ABA about, for their whole life and after: every QR with no closing event
    -- (CLOSED, PAYMENT_RECORDED, NEEDS_CHECK, EXPIRED), paid ones whose Payment is not saved
    -- yet included. The job closes each one: EXPIRED when ABA says unpaid after expires_at,
    -- NEEDS_CHECK when ABA gives no answer for two days after it.
    CREATE FUNCTION app.aba_qr_to_check(p_property uuid, p_actor uuid)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DECLARE
        v_rows jsonb;
    BEGIN
        PERFORM app.require_telegram_right(p_actor, 'telegram.operate', p_property);
        SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'tran_id', request.tran_id, 'invoice_id', request.invoice_id,
                'customer_id', invoice.customer_id, 'lease_id', invoice.lease_id,
                'amount_usd_cents', request.amount_usd_cents, 'expires_at', request.expires_at,
                'created_at', request.created_at,
                'paid', EXISTS (SELECT 1 FROM app.aba_qr_events AS event
                                WHERE event.request_id = request.id AND event.kind = 'PAID'))
                ORDER BY request.created_at), '[]'::jsonb)
        INTO v_rows
        FROM app.aba_qr_requests AS request
        JOIN app.invoices AS invoice ON invoice.id = request.invoice_id
        WHERE request.property_id = p_property
          AND NOT EXISTS (SELECT 1 FROM app.aba_qr_events AS event
                          WHERE event.request_id = request.id
                            AND event.kind IN ('CLOSED', 'PAYMENT_RECORDED', 'NEEDS_CHECK', 'EXPIRED'));
        RETURN v_rows;
    END $$;
"""

RUNTIME = (
    "app.aba_invoice_for_outbox(uuid, uuid, uuid)",
    "app.aba_record_qr(uuid, uuid, text, bigint, text, timestamptz, uuid)",
    "app.aba_record_qr_event(uuid, text, text, jsonb, uuid)",
    "app.aba_qr_to_check(uuid, uuid)",
    "app.aba_payment_method(uuid, text, uuid)",
)
INTERNAL = ("app.aba_qr_open(uuid)",)


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(FUNCTIONS)
    for signature in RUNTIME + INTERNAL:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    for signature in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("the ABA Invoice QR migration is forward-only")
