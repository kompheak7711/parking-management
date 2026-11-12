# ruff: noqa: E501
"""Simpler Invoice types: Rent, Utilities, Short stay, Products, Damage, Other charges (DL-221).

The owner asked on 11 Nov 2026 why Settings > Invoice types had First Rent and Services but no
Short stay or Products, and why product sales showed "Miscellaneous". On the card of 11 Nov 2026
the owner chose "Yes, use all 4":

1. First Rent joins Rent: every Rent Invoice, the first one too, follows the one Rent switch.
2. A new type Short stay, late payment No.
3. A new type Products (an Invoice made when the Customer signs a Quotation), late payment Yes.
4. Short-stay damage is a Damage Invoice and follows the Damage switch.

Services is never the type of an Invoice (Monthly services are lines on the Rent Invoice), so it
and First Rent are no longer used: ``in_use`` is No and Settings does not list them. Their rows
stay (Invoice types are never removed). Miscellaneous is still used by the move-out cleaning
charge, extra move-out charges and refund pay-back charges; it is renamed "Other charges".

``app.invoice_type_of(invoice)`` names the type of one Invoice; the late-payment checks and the
Invoice, Receive payment and Receipt reads use it. An Invoice's category, lines, money and ledger
do not change: only the type a screen shows and the late-payment switch it follows.

Forward-only and additive.
"""

import re
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270716_390"
down_revision: str | None = "20270715_387"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = r"""
ALTER TABLE app.invoice_types ADD COLUMN in_use boolean NOT NULL DEFAULT true;
COMMENT ON COLUMN app.invoice_types.in_use IS
    'DL-221 (owner 11/11/2026): No = no Invoice gets this type any more; Settings does not list it.';

UPDATE app.invoice_types AS kind SET in_use = false, version = kind.version + 1,
    updated_at = statement_timestamp()
WHERE kind.code IN ('FIRST_RENT', 'SERVICES');
UPDATE app.invoice_types AS kind SET name_en = 'Rent', name_kh = 'ថ្លៃឈ្នួល', sort_order = 1,
    version = kind.version + 1, updated_at = statement_timestamp()
WHERE kind.code = 'RENT';
UPDATE app.invoice_types AS kind SET sort_order = 2, version = kind.version + 1,
    updated_at = statement_timestamp()
WHERE kind.code = 'UTILITIES';
UPDATE app.invoice_types AS kind SET sort_order = 5, version = kind.version + 1,
    updated_at = statement_timestamp()
WHERE kind.code = 'DAMAGE';
UPDATE app.invoice_types AS kind SET name_en = 'Other charges', name_kh = 'ថ្លៃផ្សេងៗ',
    sort_order = 6, version = kind.version + 1, updated_at = statement_timestamp()
WHERE kind.code = 'MISCELLANEOUS';
UPDATE app.invoice_types AS kind SET sort_order = 7, version = kind.version + 1,
    updated_at = statement_timestamp()
WHERE kind.code = 'FIRST_RENT';
UPDATE app.invoice_types AS kind SET sort_order = 8, version = kind.version + 1,
    updated_at = statement_timestamp()
WHERE kind.code = 'SERVICES';
INSERT INTO app.invoice_types (code, name_en, name_kh, late_payment, sort_order) VALUES
    ('SHORT_STAY', 'Short stay', 'ការស្នាក់នៅខ្លី', false, 3),
    ('PRODUCTS', 'Products', 'ផលិតផល', true, 4);
"""

FUNCTIONS = r"""
-- The type of one Invoice (DL-221).
CREATE FUNCTION app.invoice_type_of(p_invoice uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT CASE
        WHEN invoice.primary_category IN ('RENT', 'SERVICE_CHARGES') THEN 'RENT'
        WHEN invoice.primary_category = 'UTILITIES' THEN 'UTILITIES'
        WHEN invoice.primary_category = 'DAMAGE_CHARGES' THEN 'DAMAGE'
        WHEN app.short_stay_invoice_kind(invoice.id) = 'SHORT_STAY_DAMAGE' THEN 'DAMAGE'
        WHEN app.short_stay_invoice_kind(invoice.id) = 'SHORT_STAY' THEN 'SHORT_STAY'
        WHEN EXISTS (SELECT 1 FROM app.quotations AS quotation
            WHERE quotation.invoice_id = invoice.id) THEN 'PRODUCTS'
        ELSE 'MISCELLANEOUS'
    END
    FROM app.invoices AS invoice
    WHERE invoice.id = p_invoice
$$;
REVOKE ALL ON FUNCTION app.invoice_type_of(uuid) FROM PUBLIC;

-- Yes when this Invoice gets the late-payment charge (an unknown type: Yes).
CREATE FUNCTION app.invoice_type_late_payment(p_invoice uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT coalesce((SELECT kind.late_payment FROM app.invoice_types AS kind
        WHERE kind.code = app.invoice_type_of(p_invoice)), true)
$$;
REVOKE ALL ON FUNCTION app.invoice_type_late_payment(uuid) FROM PUBLIC;

-- The old form, by category: the first Rent is Rent now.
CREATE OR REPLACE FUNCTION app.invoice_type_code(p_category text, p_rent_kind text) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
    SELECT CASE
        WHEN p_category IN ('RENT', 'SERVICE_CHARGES') THEN 'RENT'
        WHEN p_category = 'UTILITIES' THEN 'UTILITIES'
        WHEN p_category = 'DAMAGE_CHARGES' THEN 'DAMAGE'
        WHEN p_category = 'MISCELLANEOUS_CHARGES' THEN 'MISCELLANEOUS'
    END
$$;
"""

# Every late-payment check asks about the Invoice itself, so a short stay or a Products Invoice
# follows its own switch.
LATE_CALL = re.compile(
    r"app\.invoice_type_late_payment\(v_invoice\.primary_category,\s*v_invoice\.rent_billing_kind\)"
)
LATE_CHECKS = (
    "app.record_automatic_late_payment_charge(uuid,uuid,uuid,uuid,uuid,uuid)",
    "app.validate_automatic_late_payment_decision(uuid)",
    "app.validate_late_payment_decision()",
    "app.finalize_late_payment_decision(uuid,uuid,uuid,uuid,text,text,text,bigint,text,uuid,uuid,uuid)",
    "app.late_payment_review_snapshot(uuid)",
)

# A type no Invoice gets any more cannot be switched.
SET_LATE = "app.set_invoice_type_late_payment(uuid,text,boolean,text,uuid,uuid)"
SET_LATE_CHANGES = (
    (
        "WHERE kind.code = p_code FOR UPDATE;",
        "WHERE kind.code = p_code AND kind.in_use FOR UPDATE;",
    ),
)

# The reads that name an Invoice also give its type.
READS = {
    "app.invoice_resource_snapshot(uuid)": (
        (
            "'short_stay',app.short_stay_invoice_kind(v_invoice.id),",
            "'short_stay',app.short_stay_invoice_kind(v_invoice.id),"
            "'invoice_type',app.invoice_type_of(v_invoice.id),",
        ),
    ),
    "app.receive_payment_payable(uuid, uuid)": (
        (
            "'short_stay',app.short_stay_invoice_kind(invoice.id),",
            "'short_stay',app.short_stay_invoice_kind(invoice.id),"
            "'invoice_type',app.invoice_type_of(invoice.id),",
        ),
    ),
    "app.payment_receipt_lines(uuid, uuid, uuid)": (
        (
            "'short_stay',app.short_stay_invoice_kind(invoice.id),",
            "'short_stay',app.short_stay_invoice_kind(invoice.id),"
            "'invoice_type',app.invoice_type_of(invoice.id),",
        ),
    ),
}


def _literal_colons(sql: str) -> str:
    """Keep ``'invoice:...:issue'`` text from reading as a SQLAlchemy bind parameter."""
    return re.sub(r"(?<![:\w\\]):(?=\w)", r"\\:", sql)


def _definition(signature: str) -> str:
    return str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _patch(signature: str, changes: tuple[tuple[str, str], ...]) -> None:
    definition = _definition(signature)
    for old, new in changes:
        if definition.count(old) != 1:
            raise RuntimeError(f"{signature}: the text to change is not there once: {old}")
        definition = definition.replace(old, new)
    op.execute(_literal_colons(definition))


def _patch_late_check(signature: str) -> None:
    definition, count = LATE_CALL.subn(
        "app.invoice_type_late_payment(v_invoice.id)", _definition(signature)
    )
    if count != 1:
        raise RuntimeError(f"{signature}: the late-payment check is not there once")
    op.execute(_literal_colons(definition))


def upgrade() -> None:
    op.execute(TABLE)
    op.execute(FUNCTIONS)
    for signature in LATE_CHECKS:
        _patch_late_check(signature)
    _patch(SET_LATE, SET_LATE_CHANGES)
    for signature, changes in READS.items():
        _patch(signature, changes)


def downgrade() -> None:
    raise NotImplementedError("the Invoice types migration is forward-only")
