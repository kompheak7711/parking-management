"""Join main's Unit holder migration (421, DL-241) with the UI v81 migrations.

Main put 20270803_421 (DL-241, C2: who holds a Unit is worked out from the dates of its records;
the stored status is only the condition) after 20270802_399; ui-v81 has 399 through its join
20270802_416. This file has 416 and 421 as parents, so there is one head again.

421 changes ``app.home_page`` from the text the database holds: the Units card reads
``app.unit_status_on`` for today instead of the stored status. UI v81 migration 20270710_361
writes the whole ``app.home_page`` text again (Paid on time, Birthdays) and sits on a branch beside
421. On a new database Alembic may run 421 before 361; 361 then puts the stored status back, and
the Units card would count no Occupied or Reserved Unit. So this join checks the function and,
only when the 421 text is missing, puts it in again with the same text 421 uses. On a database
where 421 ran last, nothing changes. No other object is shared: no ui-v81 migration redefines the
other functions 421 changes, and 410 only sets ``VACANT`` where the status is ``CLEANING``, which
421 still allows. Read only: no table, row, amount or document changes. Same signature, owner and
privileges. Forward-only.

Revision ID: 20270803_417
Revises: 20270802_416, 20270803_421
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270803_417"
down_revision: str | Sequence[str] | None = ("20270802_416", "20270803_421")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOME = "app.home_page(uuid,uuid,uuid[],text[])"
# The same text migration 20270803_421 changes, and what it puts in.
UNITS_BEFORE = "            FROM app.units unit WHERE unit.property_id=p_property\n"
UNITS_AFTER = (
    "            FROM (SELECT u.id, u.property_id, u.for_rent,\n"
    "                    app.unit_status_on(u.id, v_today) AS status\n"
    "                FROM app.units u) unit WHERE unit.property_id=p_property\n"
)
NEW_MARK = "app.unit_status_on(u.id, v_today) AS status"
# What the UI v81 migrations and the 403 join put in; it must still be there after the change.
KEPT = ("'paid_on_time'", "IF 'birthdays' = ANY(p_sections) THEN")
# The letters block of main's 413, which the 403 join keeps (it reads the step twice).
LETTERS_MARK = "app.rent_notice_person_step(item->'assessment')"


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
    if LETTERS_MARK not in definition:
        raise RuntimeError(f"{HOME}: the Rent notice letters block of 413 is missing")
    if NEW_MARK in definition:
        return
    if definition.count(UNITS_BEFORE) != 1:
        raise RuntimeError(f"Unit holder source contract changed: {HOME}")
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(text(definition.replace(UNITS_BEFORE, UNITS_AFTER).replace(":", "\\:")))


def downgrade() -> None:
    raise NotImplementedError("the join of 416 and 421 is forward-only")
