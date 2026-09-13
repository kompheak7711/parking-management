"""Align recurring final-month generation with existing approved source coverage."""

from alembic import op
from sqlalchemy import text

revision = "20260914_53"
down_revision = "20260911_52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    signature = (
        "app.generate_rent_service_invoice(uuid,uuid,text,uuid,text,uuid,uuid,text,date,"
        "timestamp with time zone,uuid,uuid)"
    )
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    replacements = (
        (
            "            v_service_lock_id uuid;",
            (
                "            v_service_lock_id uuid;\n"
                "            v_processed_early_final_month boolean;"
            ),
        ),
        (
            """            IF v_lease.start_date>p_period_start OR v_lease.end_date<v_period_end
                OR (
                    v_lease.status='TERMINATED'
                    AND v_lease.actual_termination_date<v_period_end
                )
            THEN
                RAISE EXCEPTION 'Rent billing period is outside contractual Lease coverage'
                    USING ERRCODE='22023';
            END IF;""",
            """            -- Use the established source predicate after the same stable cutoff.
            -- It verifies the exact recorded BR-LEASE-021 governing command and
            -- excludes coverage already included in the initial Rent period.
            -- This exception never supplies a termination right or holdover terms.
            v_processed_early_final_month:=COALESCE(
                p_billing_kind='RECURRING' AND v_lease.status='TERMINATED'
                AND v_lease.actual_termination_date<v_lease.end_date
                AND v_lease.actual_termination_date>=p_period_start
                AND v_lease.actual_termination_date<v_period_end
                AND v_period_end=(date_trunc('month',v_lease.actual_termination_date)
                    + interval '1 month - 1 day')::date
                AND app.lease_is_billable_for_recurring_period(
                    p_lease_id,p_period_start,v_period_end,v_source_selection_cutoff
                ),false);
            IF (v_lease.start_date>p_period_start OR v_lease.end_date<v_period_end
                OR (
                    v_lease.status='TERMINATED'
                    AND v_lease.actual_termination_date<v_period_end
                )) AND NOT v_processed_early_final_month
            THEN
                RAISE EXCEPTION 'Rent billing period is outside contractual Lease coverage'
                    USING ERRCODE='22023';
            END IF;""",
        ),
        (
            """                CASE p_billing_kind WHEN 'INITIAL' THEN 'BR-RENT-015'
                    ELSE 'BR-RENT-018' END,""",
            """                CASE WHEN p_billing_kind='INITIAL' THEN 'BR-RENT-015'
                    WHEN v_processed_early_final_month THEN 'BR-RENT-024'
                    ELSE 'BR-RENT-018' END,""",
        ),
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError("Final-month billing integration source contract changed")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE retains the existing function's identity and privileges.
    # Its replay, source-lock order, issuance chronology and financial writes remain.
    op.execute(definition)

    # A recurring Rent header also carries its approved fixed-Service line.
    # Keep standalone Service provenance and every relational/chronology check.
    signature = "app.validate_invoice_issuance_lines()"
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    before = "AND v_invoice.due_date_source='BR-SVC-013'"
    after = """AND (v_invoice.due_date_source='BR-SVC-013'
                                                  OR (v_invoice.primary_category='RENT'
                                                      AND v_invoice.rent_billing_kind='RECURRING'
                                                      AND v_invoice.due_date_source='BR-RENT-024'
                                                      AND lease.actual_termination_date
                                                          <lease.end_date))"""
    if definition.count(before) != 1:
        raise RuntimeError("Final-month Service issuance source contract changed")
    op.execute(definition.replace(before, after))


def downgrade() -> None:
    raise RuntimeError("Termination final-month billing migration is forward-only")
