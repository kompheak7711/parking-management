# ruff: noqa: E501
"""The Utility Rate is chosen by the first day of the period of use (Q3, DL-230).

Owner (12 Nov 2026, DL-226, Q3 = B): a new rate is used only for use from its start date. Before,
the rate in force on the day the Invoice was made was used for the whole period, so a rate that
started after the use was over could still price it.

What changes (BR-UTIL-014):

- ``app.preview_utility_calculation`` takes the latest rate that had started on or before the
  first day of the period (the first day of the estimated time for a broken Meter). Every
  Utilities Invoice is priced by this function: the monthly run, the catch-up and the final
  Invoice at move-out.
- ``app.validate_invoice_line`` holds a Utilities line to the same choice.
- A period that started before the first rate ever set of its kind has no older price. It uses
  that first rate, and as before the Invoice can be made only once that rate has started. The
  refusal keeps its words, so the API still answers ``UTILITY_RATE_NOT_IN_EFFECT`` (DL-105).

No table and no row is changed: an issued Invoice, its lines and their stored rate stay as they
are. This migration is forward-only.

Technical choices by Claude under the owner's 2026-10-23 22:30 rule; the rule is the owner's. The
first-rate case is Claude's reading and is told to the owner with the pull request.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270727_379"
down_revision: str | None = "20270726_413"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREVIEW = "app.preview_utility_calculation(uuid,text,uuid,timestamptz,uuid)"
LINE = "app.validate_invoice_line()"

PREVIEW_PATCHES = (
    (
        "v_timezone text; v_generation_date date;",
        "v_timezone text; v_generation_date date; v_period_start date;",
    ),
    (
        "v_utility_type:=v_period.utility_type;",
        "v_utility_type:=v_period.utility_type;\n"
        "                v_period_start:=v_period.start_date;",
    ),
    (
        "SELECT case_record.id,case_record.unit_id,case_record.utility_type\n"
        "                INTO v_case_id,v_unit_id,v_utility_type",
        "SELECT case_record.id,case_record.unit_id,case_record.utility_type,\n"
        "                    case_record.unmeasured_start_date\n"
        "                INTO v_case_id,v_unit_id,v_utility_type,v_period_start",
    ),
    (
        "AND rate.effective_date<=v_generation_date",
        "AND rate.effective_date<=v_period_start",
    ),
    (
        "            IF NOT FOUND THEN\n"
        "                RAISE EXCEPTION 'Generation-date Utility Rate was not found'",
        "            IF NOT FOUND THEN\n"
        "                -- DL-230: use from before the first rate ever set has no older price.\n"
        "                SELECT rate.* INTO v_rate FROM app.utility_rates AS rate\n"
        "                WHERE rate.property_id=p_property_id\n"
        "                  AND rate.utility_type=v_utility_type\n"
        "                ORDER BY rate.effective_date,rate.id LIMIT 1;\n"
        "            END IF;\n"
        "            IF v_rate.id IS NULL OR v_rate.effective_date>v_generation_date THEN\n"
        "                RAISE EXCEPTION 'Generation-date Utility Rate was not found'",
    ),
)

LINE_PATCHES = (
    (
        "                          AND NOT EXISTS (\n"
        "                              SELECT 1 FROM app.utility_rates AS later\n"
        "                              WHERE later.property_id=rate.property_id\n"
        "                                AND later.utility_type=rate.utility_type\n"
        "                                AND later.measurement_unit_code=rate.measurement_unit_code\n"
        "                                AND later.effective_date<=v_invoice.invoice_date\n"
        "                                AND later.effective_date>rate.effective_date\n"
        "                          )\n",
        "                          -- DL-230: the latest rate that had started on the first day of\n"
        "                          -- the period, or the first rate ever set when none had.\n"
        "                          AND EXISTS (\n"
        "                              SELECT 1 FROM app.utility_consumption_periods AS used\n"
        "                              WHERE used.id=NEW.utility_consumption_period_id\n"
        "                                AND ((rate.effective_date<=used.start_date AND NOT EXISTS (\n"
        "                                    SELECT 1 FROM app.utility_rates AS later\n"
        "                                    WHERE later.property_id=rate.property_id\n"
        "                                      AND later.utility_type=rate.utility_type\n"
        "                                      AND later.effective_date<=used.start_date\n"
        "                                      AND later.effective_date>rate.effective_date\n"
        "                                )) OR (rate.effective_date>used.start_date AND NOT EXISTS (\n"
        "                                    SELECT 1 FROM app.utility_rates AS earlier\n"
        "                                    WHERE earlier.property_id=rate.property_id\n"
        "                                      AND earlier.utility_type=rate.utility_type\n"
        "                                      AND earlier.effective_date<rate.effective_date\n"
        "                                )))\n"
        "                          )\n",
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
            raise RuntimeError(f"Utility Rate source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(text(definition.replace(":", "\\:")))


def upgrade() -> None:
    _patch(PREVIEW, PREVIEW_PATCHES)
    _patch(LINE, LINE_PATCHES)


def downgrade() -> None:
    raise RuntimeError("the Utility Rate by period start migration is forward-only")
