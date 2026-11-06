"""Daily and weekly rent, phase 7 (owner test 05/11/2026): stay Invoices show "Short stay".

The owner asked why the Receipt said "ថ្លៃផ្សេងៗ Miscellaneous INV260011" for a stay. A short-stay
Invoice is an items Invoice of the type MISCELLANEOUS_CHARGES (the only items type), so every
screen named it "Miscellaneous". The type stays as it is (the Invoice rules, the totals and the
ledger key on it); the reads that name an Invoice now also say when it is a short stay:

- ``short_stay`` is SHORT_STAY for the stay, an extension, a fee or an ended credit, and
  SHORT_STAY_DAMAGE for a short-stay damage Invoice, else null;
- it is added to the Invoice read, the Receive payment list and the Receipt lines, and the
  screens print "Short stay" (ការស្នាក់នៅខ្លី) or "Short-stay damage" in place of the type.

Display only: no money, no rule. Forward-only and additive.
"""

import re
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270610_350"
down_revision: str | None = "20270609_319"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = r"""
CREATE FUNCTION app.short_stay_invoice_kind(p_invoice uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT CASE WHEN bool_or(stay.code = '4070') THEN 'SHORT_STAY_DAMAGE' ELSE 'SHORT_STAY' END
    FROM app.short_stay_invoice_accounts AS stay
    WHERE stay.invoice_id = p_invoice
    HAVING count(*) > 0
$$;
REVOKE ALL ON FUNCTION app.short_stay_invoice_kind(uuid) FROM PUBLIC;
"""

PATCHES = {
    "app.invoice_resource_snapshot(uuid)": (
        (
            "'lease_id',v_invoice.lease_id,'category',v_invoice.primary_category,",
            "'lease_id',v_invoice.lease_id,'category',v_invoice.primary_category,"
            "'short_stay',app.short_stay_invoice_kind(v_invoice.id),",
        ),
    ),
    "app.receive_payment_payable(uuid, uuid)": (
        (
            "'category',invoice.primary_category,",
            "'category',invoice.primary_category,"
            "'short_stay',app.short_stay_invoice_kind(invoice.id),",
        ),
    ),
    "app.payment_receipt_lines(uuid, uuid, uuid)": (
        (
            "'category',invoice.primary_category,",
            "'category',invoice.primary_category,"
            "'short_stay',app.short_stay_invoice_kind(invoice.id),",
        ),
    ),
}


def _literal_colons(sql: str) -> str:
    """Keep ``'invoice:...:issue'`` text from reading as a SQLAlchemy bind parameter."""
    return re.sub(r"(?<![:\w\\]):(?=\w)", r"\\:", sql)


def _patch(signature: str, changes: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for old, new in changes:
        if definition.count(old) != 1:
            raise RuntimeError(f"{signature}: the text to change is not there once: {old}")
        definition = definition.replace(old, new)
    op.execute(_literal_colons(definition))


def upgrade() -> None:
    op.execute(FUNCTIONS)
    for signature, changes in PATCHES.items():
        _patch(signature, changes)


def downgrade() -> None:
    raise NotImplementedError("Short-stay migrations are forward-only")
