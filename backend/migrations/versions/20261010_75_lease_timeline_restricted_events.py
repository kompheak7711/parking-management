"""Bounded read of restricted Lease timeline events (DL-067, slice 9f-5).

Additive only. ``app.lease_timeline_restricted`` returns Initial Rent Due Date overrides and
Rent-nonpayment events of one Lease, but only for the Property lists the application passes in:
one built from the actor's ``invoices.read`` grants and one from ``rent_nonpayment.read`` grants.
As in the existing bounded functions, the database checks the active human actor and the Property
lists; the application checks the capabilities. The runtime role gets EXECUTE on this function
only and no table privilege.
"""

from alembic import op

revision = "20261010_75"
down_revision = "20261009_74"
branch_labels = None
depends_on = None

SIGNATURE = (
    "app.lease_timeline_restricted(uuid,uuid,uuid[],uuid[],timestamp with time zone,uuid,integer)"
)


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app.lease_timeline_restricted(
            p_actor uuid,p_lease uuid,p_invoice_properties uuid[],p_nonpayment_properties uuid[],
            p_after_at timestamptz,p_after_id uuid,p_limit integer
        ) RETURNS TABLE(event_id uuid,event_kind text,occurred_at timestamptz,reason text,
            actor_id uuid,source_reference text,source_href text)
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        #variable_conflict use_column
        DECLARE v_property uuid;
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts a
                JOIN app.actor_identities i ON i.actor_id=a.actor_id
                WHERE a.actor_id=p_actor AND a.lifecycle_state='active' AND i.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Lease timeline actor is not active' USING ERRCODE='42501'; END IF;
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 101
                OR (p_after_at IS NULL)<>(p_after_id IS NULL)
            THEN RAISE EXCEPTION 'Lease timeline page is invalid' USING ERRCODE='22023'; END IF;
            SELECT u.property_id INTO v_property FROM app.leases l
                JOIN app.units u ON u.id=l.unit_id WHERE l.id=p_lease;
            IF v_property IS NULL THEN RETURN; END IF;
            RETURN QUERY
            SELECT event.* FROM (
                SELECT o.id,'lease.initial_rent_due_date_override'::text,o.occurred_at,o.reason,
                       o.actor_id,o.due_date::text,
                       '/api/v1/leases/'||o.lease_id::text||'#timeline-'||o.id::text
                FROM app.initial_rent_due_date_overrides o
                WHERE o.lease_id=p_lease AND o.property_id=v_property
                  AND v_property=ANY(COALESCE(p_invoice_properties,'{}'::uuid[]))
                UNION ALL
                SELECT e.id,'lease.rent_nonpayment_'||lower(e.event_kind),e.occurred_at,e.reason,
                       e.actor_id,e.rent_nonpayment_case_id::text,
                       '/api/v1/leases/'||c.lease_id::text||'#timeline-'||e.id::text
                FROM app.rent_nonpayment_events e
                JOIN app.rent_nonpayment_cases c ON c.id=e.rent_nonpayment_case_id
                WHERE c.lease_id=p_lease
                  AND v_property=ANY(COALESCE(p_nonpayment_properties,'{}'::uuid[]))
            ) AS event(event_id,event_kind,occurred_at,reason,actor_id,source_reference,source_href)
            WHERE p_after_at IS NULL OR (event.occurred_at,event.event_id)>(p_after_at,p_after_id)
            ORDER BY event.occurred_at,event.event_id LIMIT p_limit;
        END $$;
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO prm_runtime")


def downgrade() -> None:
    """Refuse rollback; the read function is part of the forward-only chain."""
    raise RuntimeError("Lease timeline restricted read is forward-only")
