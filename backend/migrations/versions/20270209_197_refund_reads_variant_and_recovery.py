"""The Refund reads name the draft variant and the recovery charge (V1-056 slice 11c-1).

Two read changes for the slice 11c staff screens; no table, command or privilege of an existing
function changes.

1. `app.usd_refund_source` (`GET /refund-sources/{CREDIT|PAYMENT}/{id}`) named the payer as the
   recipient for every Credit. A Credit that a credit Adjustment released to a Customer other than
   the payer (BR-CREDIT-014, `app.credit_customer_refund_basis`) is refunded only to that Customer,
   through a `CREDIT_CUSTOMER` draft. The read now names that Customer and adds `refund_variant`:
   `CREDIT_CUSTOMER` for such a Credit, `USD` for every other Payment or Credit source
   (plan note of the 8f review round 1).
2. `app.refund_resource` left out `recovery_obligation_id` from each correction (the screens then
   accepted exactly the existing keys). Each correction item now carries `recovery`: for a
   `RECOVERED_BY_CHARGE` correction, the recovery charge (its obligation, Invoice, Invoice number
   and status, Customer, Lease or none, amount, the kind of charge and its due date); otherwise
   null (plan read item of the 10e-1c review round 1). The financial action context reads only
   value corrections and their reversals, so it is unchanged.
"""

from alembic import op
from sqlalchemy import text

revision = "20270209_197"
down_revision = "20270208_196"
branch_labels = None
depends_on = None

SQL = """
    -- The recovery charge of one RECOVERED_BY_CHARGE Refund correction, as the Refund read shows
    -- it; null for any other correction. A VOID recovery Invoice frees its charge to be billed
    -- again, so the charge may have lines on more than one Invoice: the Invoice fields all come
    -- from one of them, an Invoice that is not VOID first, then the newest (review round 1).
    CREATE FUNCTION app.refund_correction_recovery(p_refund_correction uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog
    SET "TimeZone"='UTC' AS $$
        SELECT (app.refund_recovery_json(correction.id)-'invoice_id'-'due_date')||jsonb_build_object(
            'invoice_id',invoice.id,'due_date',invoice.due_date,
            'invoice_number',invoice.invoice_number,'invoice_status',invoice.status)
        FROM app.refund_corrections correction
        JOIN app.invoice_lines line ON line.authorized_obligation_id=correction.recovery_obligation_id
        JOIN app.invoices invoice ON invoice.id=line.invoice_id
        WHERE correction.id=p_refund_correction AND correction.correction_kind='RECOVERED_BY_CHARGE'
        ORDER BY invoice.status='VOID',invoice.created_at DESC,invoice.id DESC
        LIMIT 1
    $$;
"""

INTERNAL = ("app.refund_correction_recovery(uuid)",)

PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.usd_refund_source(uuid,uuid,text,uuid)",
        (
            (
                "'recipient_customer_id',v_payment.payer_customer_id,'property_id',p_property_id,",
                "'recipient_customer_id',COALESCE((app.credit_customer_refund_basis(\n"
                "                    CASE WHEN p_kind='CREDIT' THEN p_source_id END)->>'customer_id')::uuid,\n"
                "                    v_payment.payer_customer_id),\n"
                "                -- V1-056 slice 11c-1 (BR-CREDIT-014): the draft variant that refunds this source.\n"
                "                'refund_variant',CASE WHEN p_kind='CREDIT'\n"
                "                    AND app.credit_customer_refund_basis(p_source_id) IS NOT NULL\n"
                "                    THEN 'CREDIT_CUSTOMER' ELSE 'USD' END,\n"
                "                'property_id',p_property_id,",
            ),
        ),
    ),
    (
        "app.refund_resource(uuid,uuid,uuid,integer,timestamp with time zone,uuid)",
        (
            (
                "'items',COALESCE(jsonb_agg(to_jsonb(page)-'page_row'-'recovery_obligation_id' ORDER BY page_row)",
                "'items',COALESCE(jsonb_agg((to_jsonb(page)-'page_row'-'recovery_obligation_id')\n"
                "                        ||jsonb_build_object('recovery',app.refund_correction_recovery(page.id))\n"
                "                        ORDER BY page_row)",
            ),
        ),
    ),
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Refund read contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("The Refund read migration is forward-only")
