# ruff: noqa: E501
"""Daily and weekly rent, phase 6 step 4c: change a stay to a Lease, with $50 off the first month.

The owner's rule (PRD 03/11/2026): a daily or weekly guest who changes to a Lease gets
SS_LEASE_FIRST_MONTH_OFF ($50) off the first month.

1. The desk makes the guest's Lease draft the usual way (Leases > New Lease, the guest as Primary
   Tenant), then links it on the booking page while the guest is in or after the check-out. The
   amount is the rule of that day and is kept with the link; one Lease per stay, one stay per
   Lease.
2. Sign Lease (one step, DL-100) then asks for the money due less the $50: the Initial Rent Invoice
   is made as always and gets a credit adjustment of $50 on its Rent line before the money pays
   it, so the Invoice, the Receipt and the reports all show the $50 off. The signing preview shows
   it as its own line.

Sign Lease and its preview are patched in place (CREATE OR REPLACE with the same signature, the
way migration 67 patched adjust_invoice); a Lease without a link signs exactly as before.
Technical choices by Claude under the owner's 2026-10-23 22:30 rule. Forward-only and additive.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270605_315"
down_revision: str | None = "20270604_314"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USED = ("SS_LEASE_FIRST_MONTH_OFF",)

PREVIEW = "app.lease_signing_preview(uuid,uuid)"
SIGN = "app.sign_lease_with_payment(uuid,uuid,uuid,text,uuid,integer,uuid[],text,jsonb,boolean)"

PREVIEW_REPLACEMENTS = (
    (
        "                    'total_usd_cents', v_total,\n",
        "                    'total_usd_cents', v_total - app.short_stay_lease_off(p_lease_id),\n"
        "                    'short_stay_off_usd_cents', app.short_stay_lease_off(p_lease_id),\n",
    ),
)

SIGN_REPLACEMENTS = (
    (
        "            v_invoice_id := (v_invoice ->> 'invoice_id')::uuid;\n"
        "            IF (v_invoice ->> 'total_usd_cents')::bigint IS DISTINCT FROM v_rent THEN",
        "            v_invoice_id := (v_invoice ->> 'invoice_id')::uuid;\n"
        "            -- A daily guest who changes to a Lease: $50 off the first month (step 4c).\n"
        "            PERFORM app.short_stay_lease_off_invoice(p_property_id, p_lease_id, v_invoice_id,\n"
        "                p_actor_id);\n"
        "            IF (v_invoice ->> 'total_usd_cents')::bigint - app.short_stay_lease_off(p_lease_id)\n"
        "                IS DISTINCT FROM v_rent THEN",
    ),
)

SCHEMA = r"""
CREATE TABLE app.short_stay_lease_offers (
    booking_id uuid PRIMARY KEY REFERENCES app.short_stay_bookings (id) ON DELETE RESTRICT,
    lease_id uuid NOT NULL UNIQUE REFERENCES app.leases (id) ON DELETE RESTRICT,
    off_usd_cents bigint NOT NULL CHECK (off_usd_cents > 0),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_by uuid NOT NULL REFERENCES app.actor_identities (actor_id) ON DELETE RESTRICT
);
CREATE TRIGGER short_stay_lease_offers_protect BEFORE UPDATE OR DELETE
    ON app.short_stay_lease_offers FOR EACH ROW EXECUTE FUNCTION app.reject_short_stay_change();
CREATE TRIGGER short_stay_lease_offers_truncate BEFORE TRUNCATE ON app.short_stay_lease_offers
    FOR EACH STATEMENT EXECUTE FUNCTION app.reject_short_stay_truncate();

ALTER FUNCTION app.short_stay_booking_json(uuid) RENAME TO short_stay_booking_cancel_json;
"""

FUNCTIONS = r"""
-- What comes off the first month of this Lease (0 when it is not a daily guest's Lease).
CREATE FUNCTION app.short_stay_lease_off(p_lease uuid) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT COALESCE((SELECT offer.off_usd_cents FROM app.short_stay_lease_offers AS offer
                     WHERE offer.lease_id = p_lease), 0)::bigint
$$;
REVOKE ALL ON FUNCTION app.short_stay_lease_off(uuid) FROM PUBLIC;

-- At Sign Lease: the credit adjustment on the Initial Rent Invoice's Rent line.
CREATE FUNCTION app.short_stay_lease_off_invoice(p_property uuid, p_lease uuid, p_invoice uuid,
    p_actor uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_off bigint := app.short_stay_lease_off(p_lease);
    v_line uuid;
    v_key uuid := gen_random_uuid();
    v_number text;
BEGIN
    IF v_off = 0 THEN
        RETURN;
    END IF;
    SELECT line.id INTO v_line FROM app.invoice_lines AS line
    WHERE line.invoice_id = p_invoice AND line.category = 'RENT'
      AND app.invoice_adjusted_line_obligation(line.id) >= v_off
    ORDER BY line.line_sequence, line.id LIMIT 1;
    IF v_line IS NULL THEN
        RAISE EXCEPTION 'The first month is less than the daily-guest discount' USING ERRCODE = '55000';
    END IF;
    SELECT booking.booking_number INTO v_number
    FROM app.short_stay_lease_offers AS offer
    JOIN app.short_stay_bookings AS booking ON booking.id = offer.booking_id
    WHERE offer.lease_id = p_lease;
    PERFORM app.adjust_invoice(p_property, p_invoice, v_line, p_actor, v_key,
        encode(sha256(convert_to('short-stay-lease-off:' || v_key::text, 'UTF8')), 'hex'),
        (SELECT invoice.version FROM app.invoices AS invoice WHERE invoice.id = p_invoice),
        'CREDIT', v_off, 'Short stay ' || v_number,
        'Daily guest changed to a Lease: off the first month', gen_random_uuid(),
        gen_random_uuid());
END $$;
REVOKE ALL ON FUNCTION app.short_stay_lease_off_invoice(uuid, uuid, uuid, uuid) FROM PUBLIC;

CREATE FUNCTION app.short_stay_booking_json(p_booking uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT app.short_stay_booking_cancel_json(booking.id) || jsonb_build_object(
        'lease_off_usd_cents', app.short_stay_rule('SS_LEASE_FIRST_MONTH_OFF',
            timezone(property.timezone_name, statement_timestamp())::date),
        'lease_offer', (SELECT jsonb_build_object('lease_id', lease.id,
                'off_usd_cents', offer.off_usd_cents, 'lease_status', lease.status,
                'start_date', lease.start_date, 'unit_number', unit.unit_number)
            FROM app.short_stay_lease_offers AS offer
            JOIN app.leases AS lease ON lease.id = offer.lease_id
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE offer.booking_id = booking.id),
        'lease_drafts', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('lease_id', lease.id,
                'unit_number', unit.unit_number, 'start_date', lease.start_date,
                'monthly_rent_usd_cents', lease.monthly_rent_usd_cents)
                ORDER BY lease.start_date NULLS LAST, lease.id)
            FROM app.leases AS lease
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.primary_tenant_id = booking.customer_id AND lease.status = 'DRAFTED'
              AND unit.property_id = booking.property_id
              AND NOT EXISTS (SELECT 1 FROM app.short_stay_lease_offers AS taken
                              WHERE taken.lease_id = lease.id)), '[]'::jsonb))
    FROM app.short_stay_bookings AS booking
    JOIN app.properties AS property ON property.id = booking.property_id
    WHERE booking.id = p_booking
$$;
REVOKE ALL ON FUNCTION app.short_stay_booking_json(uuid) FROM PUBLIC;

-- Link the guest's Lease draft: $50 off its first month at signing.
CREATE FUNCTION app.link_short_stay_lease(p_property uuid, p_booking uuid, p_link jsonb,
    p_actor uuid, p_correlation uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_today date := app.require_product_right(p_actor, 'short_stays.desk', p_property);
    v_row app.short_stay_bookings%ROWTYPE := app.short_stay_locked(p_property, p_booking, NULL);
    v_lease app.leases%ROWTYPE;
    v_off bigint;
BEGIN
    BEGIN
        SELECT lease.* INTO v_lease FROM app.leases AS lease
        JOIN app.units AS unit ON unit.id = lease.unit_id
        WHERE lease.id = (p_link ->> 'lease_id')::uuid AND unit.property_id = p_property
        FOR UPDATE OF lease;
    EXCEPTION WHEN data_exception THEN
        RAISE EXCEPTION 'the Lease does not exist' USING ERRCODE = '22023';
    END;
    IF v_lease.id IS NULL THEN
        RAISE EXCEPTION 'the Lease does not exist' USING ERRCODE = '22023';
    END IF;
    IF v_row.status NOT IN ('CHECKED_IN', 'CHECKED_OUT') THEN
        RAISE EXCEPTION 'A guest changes to a Lease while in or after the stay' USING ERRCODE = '55000';
    END IF;
    IF v_lease.primary_tenant_id <> v_row.customer_id OR v_lease.status <> 'DRAFTED' THEN
        RAISE EXCEPTION 'Link a Lease draft of this guest' USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM app.short_stay_lease_offers AS offer
               WHERE offer.booking_id = p_booking OR offer.lease_id = v_lease.id) THEN
        RAISE EXCEPTION 'This stay or this Lease is already linked' USING ERRCODE = '55000';
    END IF;
    v_off := app.short_stay_rule('SS_LEASE_FIRST_MONTH_OFF', v_today);
    IF v_off < 1 THEN
        RAISE EXCEPTION 'There is no daily-guest discount today' USING ERRCODE = '55000';
    END IF;
    INSERT INTO app.short_stay_lease_offers (booking_id, lease_id, off_usd_cents, created_by)
    VALUES (p_booking, v_lease.id, v_off, p_actor);
    PERFORM app.short_stay_event(p_booking, 'LEASE_LINKED', p_actor, NULL,
        jsonb_build_object('lease_id', v_lease.id, 'off_usd_cents', v_off));
    PERFORM app.product_audit(p_property, p_actor, v_today, 'short_stay.lease_linked',
        'short_stay_booking', p_booking, 'Daily guest changes to a Lease', 'short_stays.desk', NULL,
        jsonb_build_object('lease_id', v_lease.id, 'off_usd_cents', v_off),
        COALESCE(p_correlation, gen_random_uuid()));
    RETURN app.short_stay_booking_json(p_booking);
END $$;
"""

ACTIONS = ("app.link_short_stay_lease(uuid, uuid, jsonb, uuid, uuid)",)


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Sign Lease source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(FUNCTIONS)
    _patch(PREVIEW, PREVIEW_REPLACEMENTS)
    _patch(SIGN, SIGN_REPLACEMENTS)
    for signature in ACTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    codes = ", ".join(_text(code) for code in USED)
    op.execute(f"UPDATE app.business_rule_names SET used_by_app = true WHERE code IN ({codes})")


def downgrade() -> None:
    raise RuntimeError("Short stays step 4c migration is forward-only")
