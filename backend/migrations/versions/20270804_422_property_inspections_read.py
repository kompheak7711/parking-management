"""Inspections page: one read for the whole Property (owner 16/11/2026, Property screen review).

The Inspections page listed nothing: move-out inspections could only be read one Lease at a time
and the Staff bot's Unit checks had no read at all. ``app.property_inspections_read`` gives the
page both lists for one Property, newest first, at most 200 of each:

- move-out inspections still in force (one that a later inspection replaced is left out), with
  the Lease number, the Unit, the main tenant, the date and how many findings;
- Unit checks sent from the Staff bot, with the Unit, the date, the kind, who checked and the
  Problem report each finding made.

It needs "Read Units" (``units.read``), the right of the Inspections menu item. Read only: no
table changes, nothing is written. The Joint Inspection records (DL-201) come later and add to
this page. Forward-only.

Revision ID: 20270804_422
Revises: 20270806_430
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270804_422"
down_revision: str | Sequence[str] | None = "20270806_430"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the read for the Inspections page."""
    op.execute(
        """
        CREATE FUNCTION app.property_inspections_read(p_property uuid, p_actor uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog SET timezone = 'UTC' AS $$
        DECLARE
            v_day date := app.require_product_right(p_actor, 'units.read', p_property);
            v_move_outs jsonb;
            v_checks jsonb;
        BEGIN
            SELECT COALESCE(jsonb_agg(row_data ORDER BY sort_date DESC, sort_at DESC, sort_id), '[]')
            INTO v_move_outs
            FROM (
                SELECT inspection.inspection_date AS sort_date,
                       inspection.completed_at AS sort_at,
                       inspection.id AS sort_id,
                       jsonb_build_object(
                           'inspection_id', inspection.id,
                           'lease_id', lease.id,
                           'lease_number', number.lease_number,
                           'unit_id', unit.id,
                           'unit_number', unit.unit_number,
                           'tenant_name', customer.legal_name,
                           'inspection_date', inspection.inspection_date,
                           'findings', (
                               SELECT count(*) FROM app.inspection_damage_findings AS finding
                               WHERE finding.inspection_id = inspection.id
                           )
                       ) AS row_data
                FROM app.move_out_inspections AS inspection
                JOIN app.leases AS lease ON lease.id = inspection.lease_id
                JOIN app.units AS unit ON unit.id = lease.unit_id
                LEFT JOIN app.lease_numbers AS number ON number.lease_id = lease.id
                LEFT JOIN app.customers AS customer ON customer.id = lease.primary_tenant_id
                WHERE inspection.property_id = p_property
                  AND NOT EXISTS (
                      SELECT 1 FROM app.move_out_inspections AS later
                      WHERE later.supersedes_inspection_id = inspection.id
                  )
                ORDER BY inspection.inspection_date DESC, inspection.completed_at DESC,
                         inspection.id
                LIMIT 200
            ) AS page;

            SELECT COALESCE(jsonb_agg(row_data ORDER BY sort_date DESC, sort_at DESC, sort_id), '[]')
            INTO v_checks
            FROM (
                SELECT unit_check.check_date AS sort_date,
                       unit_check.created_at AS sort_at,
                       unit_check.id AS sort_id,
                       jsonb_build_object(
                           'check_id', unit_check.id,
                           'unit_id', unit.id,
                           'unit_number', unit.unit_number,
                           'check_date', unit_check.check_date,
                           'kind', unit_check.kind,
                           'findings', unit_check.findings,
                           'checked_by_en', employee.name_en,
                           'checked_by_km', employee.name_km,
                           'reports', COALESCE((
                               SELECT jsonb_agg(jsonb_build_object(
                                   'report_id', report.id,
                                   'report_number', report.report_number
                               ) ORDER BY report.report_number)
                               FROM app.staff_unit_check_findings AS finding
                               JOIN app.problem_reports AS report ON report.id = finding.report_id
                               WHERE finding.check_id = unit_check.id
                           ), '[]')
                       ) AS row_data
                FROM app.staff_unit_checks AS unit_check
                JOIN app.units AS unit ON unit.id = unit_check.unit_id
                JOIN app.employees AS employee ON employee.id = unit_check.employee_id
                WHERE unit_check.property_id = p_property
                ORDER BY unit_check.check_date DESC, unit_check.created_at DESC, unit_check.id
                LIMIT 200
            ) AS page;

            RETURN jsonb_build_object(
                'as_of', v_day,
                'move_outs', v_move_outs,
                'unit_checks', v_checks
            );
        END $$;

        REVOKE ALL ON FUNCTION app.property_inspections_read(uuid, uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.property_inspections_read(uuid, uuid) TO prm_runtime;
        """
    )


def downgrade() -> None:
    raise NotImplementedError("20270804_422 property inspections read is forward-only")
