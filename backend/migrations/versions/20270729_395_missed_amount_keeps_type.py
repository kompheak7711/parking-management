"""An amount missed on a fully paid line keeps the type of what was missed (D3, DL-232).

Owner (12 Nov 2026, DL-226, D3). A debit Adjustment is refused on a fully paid Invoice line
(BR-INV-021). The missed amount is billed on a new one-time Invoice. Before, that Invoice was
always "Other charges", so missed Rent showed as Other charges income.

What changes (BR-INV-021):

- ``app.invoices.missed_on_invoice_line_id``: the Invoice line where the amount was missed. It
  is empty on every other Invoice, and it never changes.
- ``app.create_missed_amount_invoice_draft`` makes the one-time Invoice. The line it names must
  be fully paid, on an issued Invoice that is not Void, of the same Customer and the same Lease
  (or no Lease). The new Invoice gets the type of that Invoice. When that Invoice is itself a
  missed-amount Invoice, the new one names the first missed line.
- ``app.keep_invoice_type`` lets a one-time Invoice hold another type only when it names a
  missed line, and only the type of the Invoice of that line.
- The Invoice read names the missed Invoice (``missed_on``).
- The income report and the General Ledger count the lines of such an Invoice as what was
  missed (missed Rent is Rent income), in the month and on the day of the new Invoice.

No row is changed or deleted. This migration is forward-only.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule; the rule is the owner's.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270729_395"
down_revision: str | None = "20270728_394"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMN = r"""
ALTER TABLE app.invoices
    ADD COLUMN missed_on_invoice_line_id uuid REFERENCES app.invoice_lines(id);
COMMENT ON COLUMN app.invoices.missed_on_invoice_line_id IS
    'D3 (DL-232): the fully paid Invoice line where the amount of this one-time Invoice '
    'was missed. Empty on every other Invoice.';
CREATE INDEX invoices_missed_on_invoice_line_idx ON app.invoices (missed_on_invoice_line_id)
    WHERE missed_on_invoice_line_id IS NOT NULL;
"""

KEEP = r"""
CREATE OR REPLACE FUNCTION app.keep_invoice_type() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
DECLARE v_missed_type text;
BEGIN
    IF NEW.missed_on_invoice_line_id IS NOT NULL THEN
        SELECT source.invoice_type INTO v_missed_type
        FROM app.invoice_lines AS line
        JOIN app.invoices AS source ON source.id = line.invoice_id
        WHERE line.id = NEW.missed_on_invoice_line_id;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.invoice_type IS DISTINCT FROM OLD.invoice_type THEN
            RAISE EXCEPTION 'The Invoice type is kept as it was made' USING ERRCODE = '55000';
        END IF;
        IF NEW.missed_on_invoice_line_id IS DISTINCT FROM OLD.missed_on_invoice_line_id THEN
            RAISE EXCEPTION 'The missed line is kept as it was made' USING ERRCODE = '55000';
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
        NEW.invoice_type := coalesce(v_missed_type,
            app.invoice_type_code(NEW.primary_category, NEW.rent_billing_kind));
    END IF;
    IF NEW.invoice_type IS NULL OR NOT (
        CASE WHEN NEW.missed_on_invoice_line_id IS NOT NULL THEN
            -- D3 (DL-232): a missed amount is a one-time charge of the type of what was missed.
            NEW.primary_category = 'MISCELLANEOUS_CHARGES'
            AND NEW.invoice_type IS NOT DISTINCT FROM v_missed_type
        ELSE
            NEW.invoice_type = app.invoice_type_code(NEW.primary_category, NEW.rent_billing_kind)
            OR (NEW.primary_category = 'MISCELLANEOUS_CHARGES'
                AND NEW.invoice_type IN ('SHORT_STAY', 'PRODUCTS', 'DAMAGE'))
        END
    ) THEN
        RAISE EXCEPTION 'The Invoice type does not fit the Invoice category'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $function$;
"""

TYPED_DRAFT = (
    "app.create_items_invoice_draft_of_type("
    "uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,text,text,jsonb,text)"
)
# The typed one-time Invoice also takes the missed line. The old 13 calls still fit: the new
# parameter is empty when it is not given.
LINKED_DRAFT = (
    (
        "p_items jsonb, p_invoice_type text)",
        "p_items jsonb, p_invoice_type text, "
        "p_missed_on_invoice_line_id uuid DEFAULT NULL::uuid)",
    ),
    (
        "due_date_source,created_at,created_by,updated_at,updated_by,invoice_type)",
        "due_date_source,created_at,created_by,updated_at,updated_by,invoice_type,"
        "missed_on_invoice_line_id)",
    ),
    (
        "                p_actor_id,p_invoice_type);\n            FOR v_item IN",
        "                p_actor_id,p_invoice_type,p_missed_on_invoice_line_id);\n"
        "            FOR v_item IN",
    ),
)

MISSED_DRAFT = r"""
CREATE FUNCTION app.create_missed_amount_invoice_draft(
    p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid, p_request_digest text,
    p_invoice_id uuid, p_audit_id uuid, p_correlation_id uuid, p_customer_id uuid,
    p_lease_id uuid, p_reason text, p_evidence_reference text, p_items jsonb,
    p_missed_on_invoice_line_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $function$
DECLARE v_replay jsonb; v_source record;
BEGIN
    v_replay := app.invoice_command_replay(p_property_id, p_actor_id, 'create',
        p_idempotency_key, p_request_digest);
    IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
    PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
    IF p_missed_on_invoice_line_id IS NULL OR p_customer_id IS NULL THEN
        RAISE EXCEPTION 'Invoice items are invalid' USING ERRCODE = '22023';
    END IF;
    SELECT source.status, source.customer_id, source.lease_id, source.invoice_type,
        source.missed_on_invoice_line_id AS first_missed
    INTO v_source
    FROM app.invoice_lines AS line
    JOIN app.invoices AS source ON source.id = line.invoice_id
    WHERE line.id = p_missed_on_invoice_line_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'The missed Invoice line was not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_source.status NOT IN ('UNPAID', 'PARTIALLY_PAID', 'PAID')
        OR v_source.customer_id <> p_customer_id
        OR v_source.lease_id IS DISTINCT FROM p_lease_id
    THEN
        RAISE EXCEPTION
            'A missed amount follows the Customer and the Lease of an issued Invoice'
            USING ERRCODE = '22023';
    END IF;
    -- The same test as the debit Adjustment (BR-INV-021): while the line has an amount unpaid,
    -- a debit Adjustment is the way.
    IF app.invoice_line_outstanding(p_missed_on_invoice_line_id) > 0 THEN
        RAISE EXCEPTION 'The Invoice line still has an amount unpaid' USING ERRCODE = '22023';
    END IF;
    RETURN app.create_items_invoice_draft_of_type(p_property_id, p_actor_id, p_idempotency_key,
        p_request_digest, p_invoice_id, p_audit_id, p_correlation_id, p_customer_id, p_lease_id,
        p_reason, p_evidence_reference, p_items, v_source.invoice_type,
        coalesce(v_source.first_missed, p_missed_on_invoice_line_id));
END $function$;
REVOKE ALL ON FUNCTION app.create_missed_amount_invoice_draft(
    uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,text,text,jsonb,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.create_missed_amount_invoice_draft(
    uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,text,text,jsonb,uuid) TO prm_financial;
"""

SNAPSHOT = "app.invoice_resource_snapshot(uuid)"
SNAPSHOT_MISSED = (
    (
        "'invoice_type',app.invoice_type_of(v_invoice.id),",
        "'invoice_type',app.invoice_type_of(v_invoice.id),"
        "'missed_on',(SELECT jsonb_build_object('invoice_id',source.id,"
        "'invoice_number',source.invoice_number,'line_id',missed.id) "
        "FROM app.invoice_lines AS missed "
        "JOIN app.invoices AS source ON source.id=missed.invoice_id "
        "WHERE missed.id=v_invoice.missed_on_invoice_line_id),",
    ),
)

INCOME = "app.report_income_facts(uuid,uuid,uuid[])"
# A line of a missed-amount Invoice counts as the line where the amount was missed. The month
# stays the month of the new Invoice.
INCOME_MISSED = (
    (
        "i.primary_category,\n",
        "i.primary_category, i.missed_on_invoice_line_id,\n",
    ),
    (
        "quoted.charge_id=line.authorized_obligation_id)",
        "quoted.charge_id=COALESCE(missed.authorized_obligation_id,"
        "line.authorized_obligation_id))",
    ),
    (
        "link.charge_id=line.authorized_obligation_id)",
        "link.charge_id=COALESCE(missed.authorized_obligation_id,"
        "line.authorized_obligation_id))",
    ),
    (
        "THEN 'REGULAR_SERVICE_CHARGES' ELSE line.category END AS category,",
        "THEN 'REGULAR_SERVICE_CHARGES' ELSE COALESCE(missed.category, line.category) "
        "END AS category,",
    ),
    (
        "LEFT JOIN app.utility_consumption_periods period "
        "ON period.id=line.utility_consumption_period_id\n",
        "LEFT JOIN app.utility_consumption_periods period "
        "ON period.id=line.utility_consumption_period_id\n"
        "            LEFT JOIN app.invoice_lines missed "
        "ON missed.id=invoice.missed_on_invoice_line_id\n",
    ),
)

LEDGER = "app.gl_app_record_events(uuid,date,date)"
# The income account of a line of a missed-amount Invoice is the account of the line where the
# amount was missed. Missed Rent is Rent income on the day of the new Invoice (4010).
LEDGER_MISSED = (
    (
        "coalesce(stay.code, CASE l.category\n",
        "coalesce(stay.code, missed_stay.code, CASE missed.category\n"
        "            WHEN 'RENT' THEN '4010'\n"
        "            WHEN 'UTILITIES' THEN CASE missed_rate.utility_type "
        "WHEN 'WATER' THEN '4040' ELSE '4030' END\n"
        "            WHEN 'SERVICE_CHARGES' THEN '4020'\n"
        "            WHEN 'DAMAGE_CHARGES' THEN '4070'\n"
        "            WHEN 'MISCELLANEOUS_CHARGES' THEN CASE "
        "WHEN missed_cleaning.obligation_id IS NOT NULL\n"
        "                THEN '4060' ELSE '4080' END\n"
        "        END, CASE l.category\n",
    ),
    (
        "    LEFT JOIN app.short_stay_invoice_accounts AS stay ON stay.invoice_id = i.id\n",
        "    LEFT JOIN app.short_stay_invoice_accounts AS stay ON stay.invoice_id = i.id\n"
        "    LEFT JOIN app.invoice_lines AS missed ON missed.id = i.missed_on_invoice_line_id\n"
        "    LEFT JOIN app.utility_rates AS missed_rate\n"
        "        ON missed_rate.id = missed.utility_rate_id\n"
        "    LEFT JOIN app.unit_cleaning_charges AS missed_cleaning\n"
        "        ON missed_cleaning.obligation_id = missed.authorized_obligation_id\n"
        "    LEFT JOIN app.short_stay_invoice_accounts AS missed_stay\n"
        "        ON missed_stay.invoice_id = missed.invoice_id\n",
    ),
)


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
            raise RuntimeError(f"Missed amount source contract changed: {signature}: {before}")
        definition = definition.replace(before, after)
    return definition


def _run(sql: str) -> None:
    op.execute(text(sql.replace(":", "\\:")))


def upgrade() -> None:
    op.execute(COLUMN)
    op.execute(KEEP)

    linked = _changed(TYPED_DRAFT, LINKED_DRAFT)
    op.execute(f"DROP FUNCTION {TYPED_DRAFT}")
    _run(linked)
    op.execute(
        "REVOKE ALL ON FUNCTION app.create_items_invoice_draft_of_type("
        "uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,text,text,jsonb,text,uuid) FROM PUBLIC"
    )
    op.execute(MISSED_DRAFT)

    _run(_changed(SNAPSHOT, SNAPSHOT_MISSED))
    _run(_changed(INCOME, INCOME_MISSED))
    _run(_changed(LEDGER, LEDGER_MISSED))


def downgrade() -> None:
    raise RuntimeError("the missed amount migration is forward-only")
