# ruff: noqa: E501
"""UI v81: the Home page read gets back four earlier fixes that migration 20270710_361 dropped.

Migration 20270710_361 (UI v81 round 4) added the "Paid on time" and "Birthdays" cards to
``app.home_page``. It did so with a whole new function text that was written from the text of
migration 20270303_222, so the four changes made to the function after 222 were lost:

1. ``20270319_238`` (V1-058 R7b-7, owner 2026-10-26 "Meters decide"): the "Refund due by" to-do
   of a Unit with no Meter counts from the final inspection alone.
2. ``20270323_242`` (V1-060 B2): a Refund draft or a Payment return draft with a payload the read
   does not understand counts as waiting with no amount; it no longer stops the whole Home page.
3. ``20270324_243`` (V1-060 report speed): the two Invoice lists are read once (MATERIALIZED).
4. ``20270408_258`` (V1.1, owner 2026-10-31): a Unit not for rent is not counted in the Units
   card or in the missing Meter readings.

This migration puts the four back, with the same exact texts those migrations used, and keeps
what 361 added (the ``paid_on_time`` card and the ``birthdays`` section). The function is changed
from the text the database holds; each old text must be there exactly once. Read only: no table,
row, amount or document changes. Same signature, owner, settings and privileges. Forward-only.

Revision ID: 20270714_365
Revises: 20270713_364
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270714_365"
down_revision: str | None = "20270713_364"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOME = "app.home_page(uuid,uuid,uuid[],text[])"

# 20270319_238: no Meter on the hand-back day, nothing to bill.
FINAL_BILLED_BEFORE = """                        WHERE command.lease_id=lease.id AND command.action='FINAL'
                          AND invoice.status NOT IN ('DRAFT','VOID')) AS final_billed
"""
FINAL_BILLED_AFTER = """                        WHERE command.lease_id=lease.id AND command.action='FINAL'
                          AND invoice.status NOT IN ('DRAFT','VOID'))
                    -- V1-058 R7b-7: no Meter at all on the hand-back day, nothing to bill.
                    OR EXISTS(SELECT 1 FROM app.physical_move_out_events move_out
                        WHERE move_out.lease_id=lease.id AND NOT EXISTS(
                            SELECT 1 FROM app.physical_move_out_events later
                            WHERE later.supersedes_event_id=move_out.id)
                          AND NOT EXISTS(SELECT 1 FROM app.utility_meters meter
                            WHERE meter.unit_id=move_out.unit_id
                              AND meter.installed_date<=move_out.actual_move_out_date
                              AND (meter.deactivated_date IS NULL
                                OR meter.deactivated_date>=move_out.actual_move_out_date)))
                        AS final_billed
"""

# 20270323_242: a draft payload the read does not understand gives no amount and no error.
REFUND_BEFORE = "WHEN 'REFUND' THEN (draft.payload->>'amount_usd_cents')::bigint\n"
REFUND_AFTER = (
    "WHEN 'REFUND' THEN CASE WHEN jsonb_typeof(draft.payload->'amount_usd_cents')='number'\n"
    "                        THEN CASE WHEN (draft.payload->>'amount_usd_cents')::numeric\n"
    "                                BETWEEN 0 AND 9000000000000000\n"
    "                            AND (draft.payload->>'amount_usd_cents')::numeric\n"
    "                                =trunc((draft.payload->>'amount_usd_cents')::numeric)\n"
    "                            THEN (draft.payload->>'amount_usd_cents')::numeric::bigint\n"
    "                        END END\n"
)
PAYMENT_BEFORE = "AND payment.id=(draft.payload->>'payment_id')::uuid\n"
PAYMENT_AFTER = "AND payment.id=app.draft_uuid(draft.payload->>'payment_id')\n"

# 20270324_243: each Invoice's balance functions run once.
OPEN_INVOICE_BEFORE = "WITH open_invoice AS ("
OPEN_INVOICE_AFTER = "WITH open_invoice AS MATERIALIZED ("
BILLED_BEFORE = "WITH billed AS ("
BILLED_AFTER = "WITH billed AS MATERIALIZED ("

# 20270408_258: a Unit not for rent is not counted.
UNITS_BEFORE = "            FROM app.units unit WHERE unit.property_id=p_property;\n"
UNITS_AFTER = (
    "            FROM app.units unit WHERE unit.property_id=p_property\n"
    "              -- V1.1 (owner 2026-10-31): a Unit not for rent is not counted.\n"
    "              AND unit.for_rent;\n"
)
READINGS_BEFORE = (
    "            WHERE unit.property_id=p_property AND meter.deactivated_date IS NULL\n"
)
READINGS_AFTER = (
    "            WHERE unit.property_id=p_property AND unit.for_rent\n"
    "              AND meter.deactivated_date IS NULL\n"
)

# In the order the four migrations ran.
REPLACEMENTS = (
    (FINAL_BILLED_BEFORE, FINAL_BILLED_AFTER),
    (REFUND_BEFORE, REFUND_AFTER),
    (PAYMENT_BEFORE, PAYMENT_AFTER),
    (OPEN_INVOICE_BEFORE, OPEN_INVOICE_AFTER),
    (BILLED_BEFORE, BILLED_AFTER),
    (UNITS_BEFORE, UNITS_AFTER),
    (READINGS_BEFORE, READINGS_AFTER),
)
# What migration 20270710_361 added; it must still be there after the change.
KEPT = ("'paid_on_time'", "IF 'birthdays' = ANY(p_sections) THEN")


def upgrade() -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": HOME},
        )
        .scalar_one()
    )
    for kept in KEPT:
        if definition.count(kept) != 1:
            raise RuntimeError(f"{HOME}: the UI v81 text is not there once: {kept}")
    for before, after in REPLACEMENTS:
        if definition.count(before) != 1:
            raise RuntimeError(f"{HOME}: the text to change is not there once: {before}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def downgrade() -> None:
    raise NotImplementedError("the Home page earlier-fixes migration is forward-only")
