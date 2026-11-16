# ruff: noqa: E501
"""Join main's Rent notice days migration (413, DL-237) with the UI v81 migrations.

Main put 20270726_413 (DL-237: unpaid-Rent notices on day 10, 20 and 25, termination letter on
day 30) after 20270725_378; ui-v81 has 378 through 20270725_402 and then its own 410
(Housekeeping task assign). This file has 410 and 413 as parents, so there is one head again.

413 changes ``app.home_page`` from the text the database holds: it swaps the whole letters block
for one that reads the new notice assessment. UI v81 migration 20270710_361 writes the whole
``app.home_page`` text again (Paid on time, Birthdays) and sits on a branch beside 413. On a new
database Alembic may run 413 before 361; 361 then puts the old letters block back. So this join
checks the function and, only when the 413 letters block is missing, puts it in again with the
same text 413 uses. On a database where 413 ran last, nothing changes. No other object is shared:
no ui-v81 migration redefines the other functions 413 changes, and 410 changes only Housekeeping.
Read only: no table, row, amount or document changes. Same signature, owner and privileges.
Forward-only.

Revision ID: 20270726_403
Revises: 20270725_410, 20270726_413
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270726_403"
down_revision: str | Sequence[str] | None = ("20270725_410", "20270726_413")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOME = "app.home_page(uuid,uuid,uuid[],text[])"
# The mark of the 413 letters block.
NEW_MARK = "app.rent_notice_person_step(item->'assessment')"
# The same three texts migration 20270726_413 uses.
HOME_FROM = "IF 'letters' = ANY(p_sections) THEN"
HOME_TO = "v_cards := v_cards || jsonb_build_object('letters_due'"
HOME_LETTERS = """IF 'letters' = ANY(p_sections) THEN
            -- Unpaid Rent steps a person must do (BR-LEASE-026, DL-237): a notice of day 10, 20
            -- or 25 for a Lease with no Telegram link, and the termination letter of day 30.
            -- From the same read the Rent nonpayment alert list uses.
            v_after := NULL;
            LOOP
                v_page := app.rent_nonpayment_alert_page(p_property, 100, v_after);
                SELECT v_twenty + count(*) FILTER (WHERE step.kind <> 'THIRTY_DAY_SERIOUS_DEFAULT'),
                    v_thirty + count(*) FILTER (WHERE step.kind = 'THIRTY_DAY_SERIOUS_DEFAULT')
                INTO v_twenty, v_thirty
                FROM jsonb_array_elements(v_page->'items') item
                CROSS JOIN LATERAL (SELECT app.rent_notice_person_step(item->'assessment') AS kind) step
                WHERE step.kind IS NOT NULL;
                SELECT v_todo || COALESCE(jsonb_agg(jsonb_build_object(
                        'kind', CASE WHEN step.kind = 'THIRTY_DAY_SERIOUS_DEFAULT'
                            THEN 'letter_day_30' ELSE 'letter_day_20' END,
                        'date', (item->'assessment'->'step_days'->>step.kind)::date,
                        'invoice_id', item->>'invoice_id', 'invoice_number', item->>'invoice_number',
                        'lease_id', item->>'lease_id', 'customer_id', item->>'customer_id',
                        'unit_id', unit.id, 'unit_number', unit.unit_number,
                        'customer_name', customer.legal_name)), '[]'::jsonb)
                INTO v_todo
                FROM jsonb_array_elements(v_page->'items') item
                CROSS JOIN LATERAL (SELECT app.rent_notice_person_step(item->'assessment') AS kind) step
                JOIN app.leases lease ON lease.id=(item->>'lease_id')::uuid
                JOIN app.units unit ON unit.id=lease.unit_id
                JOIN app.customers customer ON customer.id=(item->>'customer_id')::uuid
                WHERE step.kind IS NOT NULL;
                EXIT WHEN v_page->>'next_cursor' IS NULL;
                v_after := (v_page->>'next_cursor')::uuid;
            END LOOP;
            """
# What the UI v81 migrations put in; it must still be there after the change.
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
    if NEW_MARK in definition:
        return
    if definition.count(HOME_FROM) != 1 or definition.count(HOME_TO) != 1:
        raise RuntimeError(f"Rent notice source contract changed: {HOME}")
    start, end = definition.index(HOME_FROM), definition.index(HOME_TO)
    if start > end:
        raise RuntimeError(f"Rent notice source contract changed: {HOME}")
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(text((definition[:start] + HOME_LETTERS + definition[end:]).replace(":", "\\:")))


def downgrade() -> None:
    raise NotImplementedError("the join of 410 and 413 is forward-only")
