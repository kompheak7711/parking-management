# ruff: noqa: E501
"""HRIS: the same ID number at Add employee, and two indexes by person (owner 2026-11-06).

1. Add employee looks for another employee of the Property whose newest ID details carry the
   same ID number (spaces and letter case do not count). Owner 14:09 ("ok" to the
   recommendation):
   - the other person still works here, or leaves on or after the new start date: the save
     stops ("This ID number belongs to E-003 Sok Mara, who still works here");
   - the other person has left: the save needs hire_again, so the form asks "Hire again?"
     first ("This ID number belonged to E-003 Sok Mara, who left on 30/06/2026").
2. Indexes on payslips and payroll lines by person, for "my payslips" in the Staff bot
   (database review 06/11/2026, foreign-key indexes).

Technical choices by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270505_305"
down_revision: str | None = "20270504_304"
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


INDEXES = """
    CREATE INDEX payslips_employee_idx ON app.payslips (employee_id);
    CREATE INDEX payroll_lines_employee_idx ON app.payroll_lines (employee_id);

    -- The ID number as it is compared: no spaces, capital letters.
    CREATE FUNCTION app.hr_id_key(p_number text) RETURNS text
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
        SELECT upper(regexp_replace(coalesce(p_number, ''), '\\s', '', 'g'))
    $$;
    REVOKE ALL ON FUNCTION app.hr_id_key(text) FROM PUBLIC;
"""

ADD_EMPLOYEE = "app.hr_add_employee(uuid, jsonb, uuid, uuid)"
ADD_EMPLOYEE_PATCHES = (
    (
        """        v_birth date;
""",
        """        v_birth date;
        v_same record;
""",
    ),
    (
        """            RAISE EXCEPTION 'Add a photo of the ID card or passport' USING ERRCODE = '22023';
        END IF;""",
        """            RAISE EXCEPTION 'Add a photo of the ID card or passport' USING ERRCODE = '22023';
        END IF;
        -- Owner 06/11 14:09: one person is not hired twice at the same time; a leaver may come back.
        SELECT employee.employee_code, employee.name_en,
            app.hr_left_on(employee.id) AS left_on INTO v_same
        FROM app.employees AS employee
        JOIN LATERAL (SELECT record.id_number FROM app.employee_identity_records AS record
            WHERE record.employee_id = employee.id
            ORDER BY record.created_at DESC LIMIT 1) AS newest ON true
        WHERE employee.property_id = p_property
          AND app.hr_id_key(newest.id_number) = app.hr_id_key(p_body #>> '{identity,id_number}')
        ORDER BY app.hr_left_on(employee.id) DESC NULLS FIRST, employee.employee_code
        LIMIT 1;
        IF FOUND THEN
            IF v_same.left_on IS NULL OR v_same.left_on >= v_start THEN
                RAISE EXCEPTION 'This ID number belongs to % %, who still works here',
                    v_same.employee_code, v_same.name_en USING ERRCODE = '22023';
            END IF;
            IF coalesce(p_body ->> 'hire_again', '') <> 'true' THEN
                RAISE EXCEPTION 'This ID number belonged to % %, who left on %. Hire again?',
                    v_same.employee_code, v_same.name_en, to_char(v_same.left_on, 'DD/MM/YYYY')
                    USING ERRCODE = '22023';
            END IF;
        END IF;""",
    ),
)


def upgrade() -> None:
    op.execute(INDEXES)
    _patch(ADD_EMPLOYEE, ADD_EMPLOYEE_PATCHES)


def downgrade() -> None:
    raise RuntimeError("HRIS same ID number migration is forward-only")
