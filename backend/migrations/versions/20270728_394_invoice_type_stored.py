"""The Invoice type is kept on the Invoice (T1, DL-231).

Owner (12 Nov 2026, DL-226): seven types are kept on the Invoice: Rent, Utilities, Short stay,
Products, Damage, Late-payment, Other charges. The line keeps its category. Before, the type was
worked out from the category and the links each time it was read (DL-221).

What changes (BR-INV-016):

- ``app.invoices.invoice_type`` (a code of ``app.invoice_types``, never empty). Every Invoice that
  exists gets the type the old rule gave it. Nothing else of an Invoice is touched: no number, no
  amount, no status, no date and no version.
- A new Invoice gets its type when it is made, and the type never changes after that. The type of
  the category is the usual one. The database's own flows state the three types a category
  cannot tell: Products (a signed Quotation), Short stay, and Damage for the damage of a short
  stay. No app role may state a type.
- A Quotation and each short-stay record may only name an Invoice of their own type.
- ``app.invoice_type_of`` reads the kept type, so every read and every late-payment check uses
  it. The old rule stays as ``app.invoice_type_from_links`` for the tests.
- The seventh type, Late-payment, is added. No Invoice gets it yet and Settings does not list it
  (``in_use`` No): it starts with the late-payment charge as an Invoice (L1).

No row is deleted. This migration is forward-only.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule; the rule is the owner's.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270728_394"
down_revision: str | None = "20270727_379"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = r"""
UPDATE app.invoice_types AS kind SET sort_order = 9, version = kind.version + 1,
    updated_at = statement_timestamp()
WHERE kind.code = 'SERVICES';
UPDATE app.invoice_types AS kind SET sort_order = 8, version = kind.version + 1,
    updated_at = statement_timestamp()
WHERE kind.code = 'FIRST_RENT';
UPDATE app.invoice_types AS kind SET sort_order = 7, version = kind.version + 1,
    updated_at = statement_timestamp()
WHERE kind.code = 'MISCELLANEOUS';
INSERT INTO app.invoice_types (code, name_en, name_kh, late_payment, sort_order, in_use) VALUES
    ('LATE_PAYMENT', 'Late-payment', 'ថ្លៃពិន័យបង់យឺត', false, 6, false);
"""

COLUMN = r"""
ALTER TABLE app.invoices ADD COLUMN invoice_type text
    CONSTRAINT invoices_invoice_type_fkey REFERENCES app.invoice_types (code) ON DELETE RESTRICT;
COMMENT ON COLUMN app.invoices.invoice_type IS
    'The Invoice type (DL-231): set when the Invoice is made and never changed.';
"""

# Every Invoice that exists gets the type the old rule gave it. Only this new column is written,
# so the history guards of the table (version, actor, status) have nothing to say and are off for
# this one statement.
BACKFILL = r"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_trigger AS guard
        WHERE guard.tgrelid = 'app.invoices'::regclass AND NOT guard.tgisinternal
          AND guard.tgenabled <> 'O')
    THEN RAISE EXCEPTION 'An Invoice trigger is switched off; the type migration will not run';
    END IF;
END $$;
ALTER TABLE app.invoices DISABLE TRIGGER USER;
UPDATE app.invoices AS invoice SET invoice_type = app.invoice_type_from_links(invoice.id);
ALTER TABLE app.invoices ENABLE TRIGGER USER;
ALTER TABLE app.invoices ALTER COLUMN invoice_type SET NOT NULL;
"""

KEEP = r"""
-- The type is given when the Invoice is made and is never changed by a caller.
CREATE FUNCTION app.keep_invoice_type() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.invoice_type IS DISTINCT FROM OLD.invoice_type THEN
            RAISE EXCEPTION 'The Invoice type is kept as it was made' USING ERRCODE = '55000';
        END IF;
        -- A Draft made from another charge may get another category. When it had the usual
        -- type of its category, it gets the usual type of the new one.
        IF NEW.primary_category IS DISTINCT FROM OLD.primary_category
            AND OLD.invoice_type
                = app.invoice_type_code(OLD.primary_category, OLD.rent_billing_kind)
        THEN
            NEW.invoice_type
                := app.invoice_type_code(NEW.primary_category, NEW.rent_billing_kind);
        END IF;
    ELSIF NEW.invoice_type IS NULL THEN
        NEW.invoice_type := app.invoice_type_code(NEW.primary_category, NEW.rent_billing_kind);
    END IF;
    IF NEW.invoice_type IS NULL OR NOT (
        NEW.invoice_type = app.invoice_type_code(NEW.primary_category, NEW.rent_billing_kind)
        OR (NEW.primary_category = 'MISCELLANEOUS_CHARGES'
            AND NEW.invoice_type IN ('SHORT_STAY', 'PRODUCTS', 'DAMAGE'))
    ) THEN
        RAISE EXCEPTION 'The Invoice type does not fit the Invoice category'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.keep_invoice_type() FROM PUBLIC;
CREATE TRIGGER invoices_10_invoice_type BEFORE INSERT OR UPDATE ON app.invoices
    FOR EACH ROW EXECUTE FUNCTION app.keep_invoice_type();

-- A Quotation and each short-stay record may only name an Invoice of their own type.
CREATE FUNCTION app.check_invoice_type_of_link() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF NEW.invoice_id IS NOT NULL
        AND (TG_OP = 'INSERT' OR NEW.invoice_id IS DISTINCT FROM OLD.invoice_id)
        AND NOT EXISTS (SELECT 1 FROM app.invoices AS invoice
            WHERE invoice.id = NEW.invoice_id AND invoice.invoice_type = TG_ARGV[0])
    THEN
        RAISE EXCEPTION 'The Invoice is not of the type %', TG_ARGV[0] USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.check_invoice_type_of_link() FROM PUBLIC;
CREATE TRIGGER invoice_type_of_link BEFORE INSERT OR UPDATE OF invoice_id ON app.quotations
    FOR EACH ROW EXECUTE FUNCTION app.check_invoice_type_of_link('PRODUCTS');
CREATE TRIGGER invoice_type_of_link BEFORE INSERT OR UPDATE OF invoice_id
    ON app.short_stay_bookings
    FOR EACH ROW EXECUTE FUNCTION app.check_invoice_type_of_link('SHORT_STAY');
CREATE TRIGGER invoice_type_of_link BEFORE INSERT OR UPDATE OF invoice_id
    ON app.short_stay_extra_invoices
    FOR EACH ROW EXECUTE FUNCTION app.check_invoice_type_of_link('SHORT_STAY');
CREATE TRIGGER invoice_type_of_link BEFORE INSERT OR UPDATE OF invoice_id
    ON app.short_stay_credit_ends
    FOR EACH ROW EXECUTE FUNCTION app.check_invoice_type_of_link('SHORT_STAY');
CREATE TRIGGER invoice_type_of_link BEFORE INSERT OR UPDATE OF invoice_id
    ON app.short_stay_damages
    FOR EACH ROW EXECUTE FUNCTION app.check_invoice_type_of_link('DAMAGE');
"""

# Every read and every late-payment check asks this function; now it reads the kept type.
READ = r"""
CREATE OR REPLACE FUNCTION app.invoice_type_of(p_invoice uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT invoice.invoice_type FROM app.invoices AS invoice WHERE invoice.id = p_invoice
$$;
"""

TYPE_OF = "app.invoice_type_of(uuid)"
ITEMS_DRAFT = (
    "app.create_items_invoice_draft(uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,text,text,jsonb)"
)
ITEMS_DRAFT_ARGUMENTS = (
    "p_property_id,p_actor_id,p_idempotency_key,p_request_digest,p_invoice_id,p_audit_id,"
    "p_correlation_id,p_customer_id,p_lease_id,p_reason,p_evidence_reference,p_items"
)
STAY = "app.short_stay_invoice(uuid,uuid,uuid,text,text,jsonb,uuid)"
STAY_ARGUMENTS = "p_property,p_actor,p_customer,p_reason,p_reference,p_items,p_correlation"
BODY = "AS $function$"

# The same function with one more word: the type. Only the database's own flows call it.
TYPED_ITEMS_DRAFT = (
    (
        "FUNCTION app.create_items_invoice_draft(",
        "FUNCTION app.create_items_invoice_draft_of_type(",
    ),
    ("p_items jsonb)", "p_items jsonb, p_invoice_type text)"),
    (
        "due_date_source,created_at,created_by,updated_at,updated_by)",
        "due_date_source,created_at,created_by,updated_at,updated_by,invoice_type)",
    ),
    (
        "                p_actor_id);\n            FOR v_item IN",
        "                p_actor_id,p_invoice_type);\n            FOR v_item IN",
    ),
)
TYPED_STAY = (
    ("p_correlation uuid)", "p_correlation uuid, p_invoice_type text)"),
    (
        "PERFORM app.create_items_invoice_draft(p_property,",
        "PERFORM app.create_items_invoice_draft_of_type(p_property,",
    ),
    ("        p_items);", "        p_items, p_invoice_type);"),
)
CALLERS = {
    "app.sign_quotation(uuid,uuid,integer,date,jsonb,uuid,uuid)": (
        (
            "PERFORM app.create_items_invoice_draft(p_property,",
            "PERFORM app.create_items_invoice_draft_of_type(p_property,",
        ),
        (
            "'Quotation ' || v_quotation.quotation_number, v_items);",
            "'Quotation ' || v_quotation.quotation_number, v_items, 'PRODUCTS');",
        ),
    ),
    "app.decide_short_stay_charge(uuid,uuid,jsonb,uuid,uuid)": (
        (
            "'unit_price_usd_cents', v_cost - v_from)),\n                v_correlation);",
            "'unit_price_usd_cents', v_cost - v_from)),\n                v_correlation, 'DAMAGE');",
        ),
    ),
    "app.decide_short_stay_damage(uuid,uuid,jsonb,uuid,uuid)": (
        (
            "'unit_price_usd_cents', v_damage.amount_usd_cents - v_from)),\n"
            "                v_correlation);",
            "'unit_price_usd_cents', v_damage.amount_usd_cents - v_from)),\n"
            "                v_correlation, 'DAMAGE');",
        ),
    ),
}


def _definition(signature: str) -> str:
    return str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _changed(signature: str, replacements: tuple[tuple[str, str], ...]) -> str:
    definition = _definition(signature)
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Invoice type source contract changed: {signature}: {before}")
        definition = definition.replace(before, after)
    return definition


def _run(sql: str) -> None:
    op.execute(text(sql.replace(":", "\\:")))


def _wrapper(signature: str, call: str) -> None:
    """Keep the function (identity, owner, privileges); its body now calls the typed one."""
    definition = _definition(signature)
    if definition.count(BODY) != 1:
        raise RuntimeError(f"Invoice type source contract changed: {signature}")
    head = definition[: definition.index(BODY)]
    _run(f"{head}{BODY}\nBEGIN\n    RETURN {call};\nEND $function$")


def upgrade() -> None:
    op.execute(TYPES)
    # The old rule under its new name, before the read function changes.
    _run(
        _changed(
            TYPE_OF, (("FUNCTION app.invoice_type_of(", "FUNCTION app.invoice_type_from_links("),)
        )
    )
    op.execute("REVOKE ALL ON FUNCTION app.invoice_type_from_links(uuid) FROM PUBLIC")
    op.execute(COLUMN)
    op.execute(BACKFILL)
    op.execute(KEEP)
    op.execute(READ)

    _run(_changed(ITEMS_DRAFT, TYPED_ITEMS_DRAFT))
    op.execute(
        "REVOKE ALL ON FUNCTION app.create_items_invoice_draft_of_type("
        "uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,text,text,jsonb,text) FROM PUBLIC"
    )
    _wrapper(
        ITEMS_DRAFT,
        f"app.create_items_invoice_draft_of_type({ITEMS_DRAFT_ARGUMENTS},'MISCELLANEOUS')",
    )

    _run(_changed(STAY, TYPED_STAY))
    op.execute(
        "REVOKE ALL ON FUNCTION app.short_stay_invoice("
        "uuid,uuid,uuid,text,text,jsonb,uuid,text) FROM PUBLIC"
    )
    _wrapper(STAY, f"app.short_stay_invoice({STAY_ARGUMENTS},'SHORT_STAY')")

    for signature, replacements in CALLERS.items():
        _run(_changed(signature, replacements))


def downgrade() -> None:
    raise RuntimeError("the Invoice type migration is forward-only")
