# ruff: noqa: E501
"""HRIS: an optional NSSF number with the ID details (owner 2026-11-07).

Owner 07/11 17:59 picked one extra employee field: the NSSF number, optional. It is kept with
the ID details (app.employee_identity_records), so only people with See salaries see it, and a
change adds a new row like every other ID change. Add employee and Change ID details may send
it; nothing requires it.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270626_306"
down_revision: str | None = "20270710_382"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
            raise RuntimeError(f"{signature} does not have the expected text")
        definition = definition.replace(before, after)
    op.execute(text(definition))


COLUMN = """
    ALTER TABLE app.employee_identity_records ADD COLUMN nssf_number text
        CHECK (nssf_number = btrim(nssf_number) AND length(nssf_number) BETWEEN 1 AND 30);
"""

ADD_IDENTITY = "app.hr_add_identity(uuid, jsonb, uuid)"
ADD_IDENTITY_PATCHES = (
    (
        "            date_of_birth, home_address, place_of_birth, created_by)",
        "            date_of_birth, home_address, place_of_birth, nssf_number, created_by)",
    ),
    (
        "                'The place of birth is at most 200 letters'),",
        "                'The place of birth is at most 200 letters'),\n"
        "            app.problem_text(p_body, 'nssf_number', 30,\n"
        "                'The NSSF number is at most 30 letters'),",
    ),
)

EMPLOYEE_READ = "app.hr_employee_read(uuid, uuid, uuid, uuid)"
EMPLOYEE_READ_PATCHES = (
    (
        "                    'place_of_birth', record.place_of_birth,",
        "                    'place_of_birth', record.place_of_birth,\n"
        "                    'nssf_number', record.nssf_number,",
    ),
)


def upgrade() -> None:
    op.execute(COLUMN)
    _patch(ADD_IDENTITY, ADD_IDENTITY_PATCHES)
    _patch(EMPLOYEE_READ, EMPLOYEE_READ_PATCHES)


def downgrade() -> None:
    raise RuntimeError("HRIS NSSF number migration is forward-only")
