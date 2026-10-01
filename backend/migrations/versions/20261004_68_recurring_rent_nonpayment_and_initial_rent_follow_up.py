# ruff: noqa: E501
"""Rent nonpayment counts from the 1st for recurring Rent only; Initial Rent gets an alert, no late fee."""

from alembic import op
from sqlalchemy import text

revision = "20261004_68"
down_revision = "20261003_67"
branch_labels = None
depends_on = None

DAY_ZERO_INVOICE = "app.rent_nonpayment_day_zero(i.id)"

PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.rent_nonpayment_source_context(uuid,timestamp with time zone)",
        (
            (
                "app.rent_nonpayment_milestone_eligible('TWENTY_DAY_WARNING',i.due_date,",
                f"app.rent_nonpayment_milestone_eligible('TWENTY_DAY_WARNING',{DAY_ZERO_INVOICE},",
            ),
            (
                "app.rent_nonpayment_milestone_eligible('THIRTY_DAY_SERIOUS_DEFAULT',i.due_date,",
                f"app.rent_nonpayment_milestone_eligible('THIRTY_DAY_SERIOUS_DEFAULT',{DAY_ZERO_INVOICE},",
            ),
        ),
    ),
    (
        "app.rent_nonpayment_alert_page(uuid,integer,uuid)",
        (
            (
                "AND timezone('Asia/Phnom_Penh',statement_timestamp())::date-i.due_date>=20",
                "AND i.rent_billing_kind='RECURRING'\n"
                f"                    AND timezone('Asia/Phnom_Penh',statement_timestamp())::date-{DAY_ZERO_INVOICE}>=20",
            ),
        ),
    ),
    (
        "app.rent_nonpayment_case_snapshot(uuid,timestamp with time zone)",
        (
            (
                "milestone_eligible('TWENTY_DAY_WARNING',c.due_date_snapshot,",
                "milestone_eligible('TWENTY_DAY_WARNING',app.rent_nonpayment_day_zero(c.invoice_id),",
            ),
            (
                "milestone_eligible('THIRTY_DAY_SERIOUS_DEFAULT',c.due_date_snapshot,",
                "milestone_eligible('THIRTY_DAY_SERIOUS_DEFAULT',app.rent_nonpayment_day_zero(c.invoice_id),",
            ),
            (
                "milestone_eligible('CURE',c.due_date_snapshot,",
                "milestone_eligible('CURE',app.rent_nonpayment_day_zero(c.invoice_id),",
            ),
        ),
    ),
    (
        "app.validate_rent_nonpayment_event()",
        (
            (
                "app.rent_nonpayment_milestone_eligible(NEW.event_kind,v_case.due_date_snapshot,",
                "app.rent_nonpayment_milestone_eligible(NEW.event_kind,app.rent_nonpayment_day_zero(v_case.invoice_id),",
            ),
        ),
    ),
    (
        "app.validate_rent_nonpayment_case()",
        (
            (
                "OR v_line.category IS DISTINCT FROM 'RENT'",
                "OR v_line.category IS DISTINCT FROM 'RENT'\n"
                "                OR v_invoice.rent_billing_kind IS DISTINCT FROM 'RECURRING'",
            ),
        ),
    ),
    (
        "app.lease_enforcement_context(uuid,uuid,text,uuid,uuid,integer,uuid)",
        (
            (
                "WHERE i.lease_id=p_lease AND line.source_lease_id=p_lease AND line.category='RENT'",
                "WHERE i.lease_id=p_lease AND line.source_lease_id=p_lease AND line.category='RENT'\n"
                "                        AND i.rent_billing_kind='RECURRING'",
            ),
        ),
    ),
    (
        "app.lease_enforcement_command(uuid,uuid,uuid,uuid,text,uuid,text,jsonb,text)",
        (
            (
                "IF v_line.category<>'RENT' OR v_line.source_lease_id IS DISTINCT FROM p_lease",
                "IF v_line.category<>'RENT' OR v_line.source_lease_id IS DISTINCT FROM p_lease\n"
                "                        OR v_invoice.rent_billing_kind IS DISTINCT FROM 'RECURRING'",
            ),
            (
                "app.rent_nonpayment_milestone_eligible(v_kind,v_case.due_date_snapshot,",
                "app.rent_nonpayment_milestone_eligible(v_kind,app.rent_nonpayment_day_zero(v_case.invoice_id),",
            ),
        ),
    ),
    (
        "app.late_payment_review_snapshot(uuid)",
        (
            (
                "v_blockers:=v_blockers||jsonb_build_array('NO_REMAINING_BALANCE');\n"
                "            END IF;\n",
                "v_blockers:=v_blockers||jsonb_build_array('NO_REMAINING_BALANCE');\n"
                "            END IF;\n"
                "            IF v_invoice.rent_billing_kind='INITIAL' THEN\n"
                "                v_blockers:=v_blockers||jsonb_build_array('INITIAL_RENT_NO_LATE_PAYMENT');\n"
                "            END IF;\n",
            ),
        ),
    ),
    (
        "app.finalize_late_payment_decision(uuid,uuid,uuid,uuid,text,text,text,bigint,text,uuid,uuid,uuid)",
        (
            (
                "            THEN RAISE EXCEPTION 'Invoice is not eligible for a late-payment Decision'",
                "                OR v_invoice.rent_billing_kind='INITIAL'\n"
                "            THEN RAISE EXCEPTION 'Invoice is not eligible for a late-payment Decision'",
            ),
        ),
    ),
    (
        "app.validate_late_payment_decision()",
        (
            (
                "OR NEW.assessed_at<v_invoice.issued_at",
                "OR v_invoice.rent_billing_kind='INITIAL'\n"
                "                OR NEW.assessed_at<v_invoice.issued_at",
            ),
        ),
    ),
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Rent nonpayment source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute("""
        -- BR-LEASE-026: day one is the 1st of the billed month, so day N is (1st - 1) + N.
        -- Initial Rent has no day zero: its 20- and 30-day milestones are never eligible.
        CREATE FUNCTION app.rent_nonpayment_day_zero(p_invoice uuid)
        RETURNS date LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT CASE WHEN invoice.rent_billing_kind='RECURRING'
                THEN invoice.billing_period_start-1 END
            FROM app.invoices invoice WHERE invoice.id=p_invoice
        $$;

        -- BR-RENT-009: unpaid Initial Rent is listed from the Asia/Phnom_Penh day after its Due Date.
        CREATE FUNCTION app.unpaid_initial_rent_alert_page(p_actor uuid,p_property uuid,
            p_limit integer,p_after uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp
            SET timezone='UTC' AS $$
        DECLARE v_items jsonb; v_business_date date;
        BEGIN
            PERFORM app.lease_enforcement_active_human(p_actor);
            IF NOT EXISTS(SELECT 1 FROM app.properties WHERE id=p_property)
            THEN RAISE EXCEPTION 'Enforcement Property not found' USING ERRCODE='P5401'; END IF;
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100
                OR p_after='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Initial Rent alert page is invalid' USING ERRCODE='P5402'; END IF;
            v_business_date:=timezone('Asia/Phnom_Penh',statement_timestamp())::date;
            SELECT COALESCE(jsonb_agg(page.item ORDER BY page.id),'[]'::jsonb) INTO v_items FROM (
                SELECT i.id,jsonb_build_object('invoice_id',i.id,'invoice_number',i.invoice_number,
                    'property_id',p_property,'lease_id',i.lease_id,'customer_id',i.customer_id,
                    'invoice_status',i.status,'due_date',i.due_date,'alert_date',i.due_date+1,
                    'remaining',jsonb_build_object('currency','USD','minor_units',balance.amount)) AS item
                FROM app.invoices i JOIN app.leases l ON l.id=i.lease_id JOIN app.units u ON u.id=l.unit_id
                CROSS JOIN LATERAL (SELECT COALESCE(sum(app.invoice_line_outstanding(line.id)),0) AS amount
                    FROM app.invoice_lines line WHERE line.invoice_id=i.id) balance
                WHERE u.property_id=p_property AND i.primary_category='RENT'
                    AND i.rent_billing_kind='INITIAL' AND i.status NOT IN ('DRAFT','VOID')
                    AND i.issued_at<=statement_timestamp() AND v_business_date>=i.due_date+1
                    AND balance.amount>0 AND (p_after IS NULL OR i.id>p_after)
                ORDER BY i.id LIMIT p_limit+1) page;
            RETURN jsonb_build_object(
                'items',CASE WHEN jsonb_array_length(v_items)>p_limit THEN v_items-p_limit ELSE v_items END,
                'next_cursor',CASE WHEN jsonb_array_length(v_items)>p_limit
                    THEN v_items->(p_limit-1)->>'invoice_id' END,
                'as_of',statement_timestamp(),'business_date',v_business_date,'timezone','Asia/Phnom_Penh');
        END $$;
    """)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in (
        "app.rent_nonpayment_day_zero(uuid)",
        "app.unpaid_initial_rent_alert_page(uuid,uuid,integer,uuid)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.unpaid_initial_rent_alert_page(uuid,uuid,integer,uuid) TO prm_runtime"
    )


def downgrade() -> None:
    raise RuntimeError("Recurring-only Rent nonpayment migration is forward-only")
