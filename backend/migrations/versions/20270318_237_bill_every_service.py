"""Bill every Service a Lease holds on its Rent Invoice (V1-058 R7b-6e; DL-075).

Revision ID: 20270318_237
Revises: 20270317_236
Create Date: 2026-10-25

Rules: BR-SVC-001, BR-SVC-012, BR-SVC-014. Until now the Rent Invoice billed only the Service whose
code is TRASH_COLLECTION; Services added in Settings since R7b-6a were recorded on the Lease but not
billed. This migration bills every other Service with the same rules as Trash Collection: a
Service is billed for a month when the Lease's term and its approval period cover that whole month
(a term or approval that covers only part of a month is refused, as for Trash Collection), at the
rate in force on the first billed day of the month (no rate is refused), prorated by days in a
move-in month and in full for a following month. Each Service gets its own Invoice line (category
SERVICE_CHARGES, named by the Service's English name) with its own calculation component, after
the Rent and Trash Collection lines: the first month's lines, then the following month's, and
within a month in the order of the Service names. The Trash Collection part of the generator is
not changed.

The generator is patched in place, as migrations 53 and 64 did: CREATE OR REPLACE keeps its
identity, owner and privileges. Every Service of the Property is already locked before the cutoff.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270318_237"
down_revision: str | None = "20270317_236"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GENERATOR = (
    "app.generate_rent_service_invoice(uuid,uuid,text,uuid,text,uuid,uuid,text,date,"
    "timestamp with time zone,uuid,uuid)"
)

DECLARATIONS = """            v_next_line_sequence smallint:=2;
            v_other record;
            v_other_term_id uuid;
            v_other_approval_id uuid;
            v_other_rate_id uuid;
            v_other_rate bigint;
            v_other_total bigint:=0;
            v_other_services uuid[]:=ARRAY[]::uuid[];
            v_other_terms uuid[]:=ARRAY[]::uuid[];
            v_other_approvals uuid[]:=ARRAY[]::uuid[];
            v_other_rate_ids uuid[]:=ARRAY[]::uuid[];
            v_other_rates bigint[]:=ARRAY[]::bigint[];
            v_other_amounts bigint[]:=ARRAY[]::bigint[];
            v_other_months smallint[]:=ARRAY[]::smallint[];
            v_other_names text[]:=ARRAY[]::text[];
            v_other_codes text[]:=ARRAY[]::text[];
            v_other_index integer;
"""

SELECTION = """            -- R7b-6e: the other Services of the Lease, billed like Trash Collection.
            FOR v_other IN
                SELECT month.month_index,month.month_start,month.month_end,
                    service.id AS service_id,service.display_name AS name_en,service.service_code
                FROM (VALUES (1::smallint,p_period_start,v_first_month_end),
                             (2::smallint,v_second_start,v_period_end))
                    AS month(month_index,month_start,month_end)
                JOIN app.property_services AS service
                  ON service.property_id=p_property_id
                 AND service.service_code<>'TRASH_COLLECTION'
                 AND service.configured_at<=v_source_selection_cutoff
                WHERE month.month_start IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM app.lease_service_terms AS term
                    JOIN app.property_service_approval_periods AS approval
                      ON approval.id=term.service_approval_period_id
                    WHERE term.property_service_id=service.id AND term.lease_id=p_lease_id
                      AND term.recorded_at<=v_source_selection_cutoff
                      AND approval.approved_at<=v_source_selection_cutoff
                      AND term.applicable_from<=month.month_end
                      AND COALESCE(term.applicable_through,month.month_end)>=month.month_start
                      AND approval.effective_from<=month.month_end
                      AND COALESCE(approval.effective_through,month.month_end)
                          >=month.month_start)
                ORDER BY month.month_index,service.display_name COLLATE "C",service.id
            LOOP
                SELECT term.id,approval.id INTO v_other_term_id,v_other_approval_id
                FROM app.lease_service_terms AS term
                JOIN app.property_service_approval_periods AS approval
                  ON approval.id=term.service_approval_period_id
                WHERE term.property_service_id=v_other.service_id AND term.lease_id=p_lease_id
                  AND term.recorded_at<=v_source_selection_cutoff
                  AND approval.approved_at<=v_source_selection_cutoff
                  AND v_other.month_start>=term.applicable_from
                  AND v_other.month_end<=COALESCE(term.applicable_through,v_other.month_end)
                  AND v_other.month_start>=approval.effective_from
                  AND v_other.month_end<=COALESCE(approval.effective_through,v_other.month_end)
                ORDER BY term.applicable_from DESC,term.id DESC LIMIT 1;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Partial-month Service configuration is unsupported'
                        USING ERRCODE='22023';
                END IF;
                SELECT rate.id,rate.monthly_rate_usd_cents INTO v_other_rate_id,v_other_rate
                FROM app.service_rates AS rate
                WHERE rate.property_service_id=v_other.service_id
                  AND rate.effective_date<=v_other.month_start
                  AND rate.occurred_at<=v_source_selection_cutoff
                ORDER BY rate.effective_date DESC,rate.id DESC LIMIT 1;
                IF NOT FOUND THEN RAISE EXCEPTION 'Applicable Service rate is missing'
                    USING ERRCODE='55000'; END IF;
                v_other_services:=v_other_services || v_other.service_id;
                v_other_terms:=v_other_terms || v_other_term_id;
                v_other_approvals:=v_other_approvals || v_other_approval_id;
                v_other_rate_ids:=v_other_rate_ids || v_other_rate_id;
                v_other_rates:=v_other_rates || v_other_rate;
                v_other_amounts:=v_other_amounts || CASE v_other.month_index
                    WHEN 1 THEN app.calculate_prorated_monthly_usd_cents(
                        v_other_rate,v_other.month_start,v_other.month_end)
                    ELSE v_other_rate END;
                v_other_months:=v_other_months || v_other.month_index;
                v_other_names:=v_other_names || v_other.name_en;
                v_other_codes:=v_other_codes || v_other.service_code;
                v_other_total:=v_other_total+v_other_amounts[cardinality(v_other_amounts)];
            END LOOP;
            v_service_total:=v_service_first+v_service_second+v_other_total;
"""

LINES = """            -- V1-058 R7b-6e: one line for each other Service and month, after the Trash
            -- Collection lines (the following-month Trash line does not move the sequence on).
            IF v_service_id_2 IS NOT NULL THEN
                v_next_line_sequence:=v_next_line_sequence+1;
            END IF;
            FOR v_other_index IN 1..cardinality(v_other_services) LOOP
                v_service_line_id:=pg_catalog.gen_random_uuid();
                INSERT INTO app.invoice_lines(
                    id,invoice_id,line_sequence,category,description,amount_usd_cents,
                    period_start,period_end,source_lease_id,property_service_id,
                    service_rate_id,lease_service_term_id,service_approval_period_id,
                    contractual_monthly_usd_cents,billable_days,calendar_days,
                    calculation_trace,created_at,created_by
                ) VALUES (
                    v_service_line_id,p_invoice_id,v_next_line_sequence,
                    'SERVICE_CHARGES',v_other_names[v_other_index],
                    v_other_amounts[v_other_index],
                    CASE v_other_months[v_other_index] WHEN 1 THEN p_period_start
                        ELSE v_second_start END,
                    CASE v_other_months[v_other_index] WHEN 1 THEN v_first_month_end
                        ELSE v_period_end END,
                    p_lease_id,v_other_services[v_other_index],
                    v_other_rate_ids[v_other_index],v_other_terms[v_other_index],
                    v_other_approvals[v_other_index],v_other_rates[v_other_index],
                    CASE v_other_months[v_other_index] WHEN 1 THEN v_first_days
                        ELSE v_second_days END,
                    CASE v_other_months[v_other_index] WHEN 1 THEN v_first_calendar_days
                        ELSE v_second_calendar_days END,
                    jsonb_build_object('service_code',v_other_codes[v_other_index],
                        'formula','monthly_usd_cents * inclusive_billable_days / calendar_days',
                        'rounding','half_up_final_usd_cent'),
                    v_source_selection_cutoff,p_actor_id
                );
                INSERT INTO app.invoice_line_calculation_components(
                    id,invoice_line_id,component_sequence,component_kind,period_start,period_end,
                    service_rate_id,service_monthly_rate_usd_cents,billable_days,calendar_days,
                    amount_usd_cents,calculation_trace,created_at,created_by
                ) VALUES (
                    pg_catalog.gen_random_uuid(),v_service_line_id,1,
                    CASE WHEN v_other_months[v_other_index]=2 THEN 'FULL_FOLLOWING_MONTH'
                        WHEN p_billing_kind='RECURRING' THEN 'FULL_RECURRING_MONTH'
                        ELSE 'PRORATED_MOVE_IN_MONTH' END,
                    CASE v_other_months[v_other_index] WHEN 1 THEN p_period_start
                        ELSE v_second_start END,
                    CASE v_other_months[v_other_index] WHEN 1 THEN v_first_month_end
                        ELSE v_period_end END,
                    v_other_rate_ids[v_other_index],v_other_rates[v_other_index],
                    CASE v_other_months[v_other_index] WHEN 1 THEN v_first_days
                        ELSE v_second_days END,
                    CASE v_other_months[v_other_index] WHEN 1 THEN v_first_calendar_days
                        ELSE v_second_calendar_days END,
                    v_other_amounts[v_other_index],
                    jsonb_build_object('service_rate_id',v_other_rate_ids[v_other_index],
                        'monthly_usd_cents',v_other_rates[v_other_index],
                        'billable_days',CASE v_other_months[v_other_index]
                            WHEN 1 THEN v_first_days ELSE v_second_days END,
                        'calendar_days',CASE v_other_months[v_other_index]
                            WHEN 1 THEN v_first_calendar_days ELSE v_second_calendar_days END,
                        'amount_usd_cents',v_other_amounts[v_other_index]),
                    v_source_selection_cutoff,p_actor_id
                );
                v_next_line_sequence:=v_next_line_sequence+1;
            END LOOP;

            UPDATE app.invoices SET status='UNPAID',
"""

REPLACEMENTS = (
    ("            v_next_line_sequence smallint:=2;\n", DECLARATIONS),
    ("            v_service_total:=v_service_first+v_service_second;\n", SELECTION),
    ("            UPDATE app.invoices SET status='UNPAID',\n", LINES),
)


def upgrade() -> None:
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": GENERATOR},
        )
        .scalar_one()
    )
    for before, after in REPLACEMENTS:
        if definition.count(before) != 1:
            raise RuntimeError("Rent and Service billing source contract changed")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def downgrade() -> None:
    raise RuntimeError("V1-058 bill every Service migration is forward-only")
