# ruff: noqa: E501
"""UI v81 round 9 (owner 12/11/2026): the Payments list and the Receipt page name the same things.

The owner saw one Receipt that the Payments list called "Move-out charges" while the Receipt page
called it a short stay, and one that the list called "Rent, Services, Deposits" while the page
said "Rent". The list splits the money by Invoice line; the page names the type of the Invoice
(DL-221). Both reads now give what the screens need to say the same words.

1. ``app.payments_period_summary``: the money paid to one-time charge lines (the line categories
   Damage and Miscellaneous) was one kind, MOVEOUT ("Move-out charges"). It is now divided by the
   type of the Invoice it paid (``app.invoice_type_of``, DL-221) into four kinds: SHORT_STAY,
   PRODUCTS, DAMAGE and OTHER ("Other charges"). The four add up to what MOVEOUT was, so the
   cards add up to the money received as before. The other kinds do not change.
2. ``app.payment_receipt_lines``: each Invoice line also gives ``parts``, the money this payment
   paid to the Invoice by line category, so the page can show Rent and Services under a Rent
   Invoice. The parts add up to the line's amount.

Read only. Both functions only read; no table, row, amount, document or ledger entry changes, and
a printed Receipt is not touched. Each function is changed from the text the database holds, so a
change made by another migration stays. Forward-only.

Revision ID: 20270713_364
Revises: 20270712_363
"""

import re
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270713_364"
down_revision: str | None = "20270712_363"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ONE_TIME = "'DAMAGE_CHARGES','MISCELLANEOUS_CHARGES'"

SUMMARY = "app.payments_period_summary(uuid,uuid,date,date,integer)"
SUMMARY_CHANGES = (
    # The columns of one payment.
    (
        "COALESCE(lines.moveout,0) AS moveout,",
        "COALESCE(lines.short_stay,0) AS short_stay,COALESCE(lines.products,0) AS products,\n"
        "                    COALESCE(lines.damage,0) AS damage,COALESCE(lines.other,0) AS other,",
    ),
    # The sums: a one-time charge line counts under the type of its Invoice.
    (
        "sum(detail.posted_amount_usd_cents) FILTER ("
        " WHERE detail.invoice_line_category_snapshot IN ("
        f" {ONE_TIME})) AS moveout",
        "sum(detail.posted_amount_usd_cents) FILTER (\n"
        "                            WHERE one_time.invoice_type='SHORT_STAY') AS short_stay,\n"
        "                        sum(detail.posted_amount_usd_cents) FILTER (\n"
        "                            WHERE one_time.invoice_type='PRODUCTS') AS products,\n"
        "                        sum(detail.posted_amount_usd_cents) FILTER (\n"
        "                            WHERE one_time.invoice_type='DAMAGE') AS damage,\n"
        "                        sum(detail.posted_amount_usd_cents) FILTER (\n"
        "                            WHERE one_time.invoice_type NOT IN (\n"
        "                                'SHORT_STAY','PRODUCTS','DAMAGE')) AS other",
    ),
    # The type is read once for each one-time charge line; any other line has none.
    (
        "ON detail.payment_allocation_id=allocation.id",
        "ON detail.payment_allocation_id=allocation.id\n"
        "                    LEFT JOIN LATERAL (\n"
        "                        SELECT COALESCE(app.invoice_type_of(allocation.invoice_id),\n"
        "                            'MISCELLANEOUS') AS invoice_type\n"
        f"                        WHERE detail.invoice_line_category_snapshot IN ({ONE_TIME})\n"
        "                    ) one_time ON true",
    ),
    # The cards.
    (
        "'MOVEOUT',jsonb_build_object('usd_cents',COALESCE(sum(moveout),0),"
        " 'payments',count(*) FILTER (WHERE moveout>0)),",
        "'SHORT_STAY',jsonb_build_object('usd_cents',COALESCE(sum(short_stay),0),\n"
        "                            'payments',count(*) FILTER (WHERE short_stay>0)),\n"
        "                        'PRODUCTS',jsonb_build_object('usd_cents',COALESCE(sum(products),0),\n"
        "                            'payments',count(*) FILTER (WHERE products>0)),\n"
        "                        'DAMAGE',jsonb_build_object('usd_cents',COALESCE(sum(damage),0),\n"
        "                            'payments',count(*) FILTER (WHERE damage>0)),\n"
        "                        'OTHER',jsonb_build_object('usd_cents',COALESCE(sum(other),0),\n"
        "                            'payments',count(*) FILTER (WHERE other>0)),",
    ),
    # The list rows.
    (
        "'MOVEOUT',NULLIF(shown.moveout,0),",
        "'SHORT_STAY',NULLIF(shown.short_stay,0),'PRODUCTS',NULLIF(shown.products,0),\n"
        "                            'DAMAGE',NULLIF(shown.damage,0),'OTHER',NULLIF(shown.other,0),",
    ),
)

RECEIPT = "app.payment_receipt_lines(uuid,uuid,uuid)"
RECEIPT_CHANGES = (
    (
        "'invoice_type',app.invoice_type_of(invoice.id),",
        "'invoice_type',app.invoice_type_of(invoice.id),\n"
        "                                'parts',(SELECT COALESCE(jsonb_object_agg(part.category,part.cents),\n"
        "                                        '{}'::jsonb)\n"
        "                                    FROM (SELECT detail.invoice_line_category_snapshot AS category,\n"
        "                                            sum(detail.posted_amount_usd_cents) AS cents\n"
        "                                        FROM app.payment_allocations piece\n"
        "                                        JOIN app.payment_allocation_details detail\n"
        "                                            ON detail.payment_allocation_id=piece.id\n"
        "                                        WHERE piece.payment_id=payment.id\n"
        "                                            AND piece.target_kind='INVOICE'\n"
        "                                            AND piece.invoice_id=invoice.id\n"
        "                                            AND detail.obligation_kind='INVOICE_LINE'\n"
        "                                            AND NOT EXISTS(\n"
        "                                                SELECT 1 FROM app.payment_allocation_reversals reversal\n"
        "                                                WHERE reversal.payment_allocation_id=piece.id)\n"
        "                                        GROUP BY detail.invoice_line_category_snapshot) part),\n"
        "                                ",
    ),
)


def _literal_colons(sql: str) -> str:
    """Keep ``HH24:MI`` and other text with a colon from reading as a SQLAlchemy bind parameter."""
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


def _anywhere(old: str) -> re.Pattern[str]:
    """The text to change, with any run of spaces and line breaks where it has a space."""
    return re.compile(r"\s+".join(re.escape(word) for word in old.split()))


def _patch(signature: str, changes: tuple[tuple[str, str], ...]) -> str:
    definition = _definition(signature)
    for old, new in changes:
        definition, count = _anywhere(old).subn(lambda _match, new=new: new, definition)
        if count != 1:
            raise RuntimeError(f"{signature}: the text to change is not there once: {old}")
    return definition


def upgrade() -> None:
    summary = _patch(SUMMARY, SUMMARY_CHANGES)
    if "moveout" in summary.lower():
        raise RuntimeError(f"{SUMMARY}: the old kind is still read")
    op.execute(_literal_colons(summary))
    op.execute(_literal_colons(_patch(RECEIPT, RECEIPT_CHANGES)))


def downgrade() -> None:
    raise NotImplementedError("the Payments paid-for migration is forward-only")
