"""Add immutable append-only audit event storage."""

from alembic import op

revision = "20260823_10"
down_revision = "20260820_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create audit storage and enforce append-only access at the database boundary."""
    op.execute(
        """
        CREATE TABLE app.audit_events (
            id uuid PRIMARY KEY,
            occurred_at timestamptz NOT NULL,
            business_date date NOT NULL,
            actor_id uuid NOT NULL,
            action text NOT NULL,
            entity_type text NOT NULL,
            entity_id uuid NOT NULL,
            reason text NOT NULL,
            authorization_reference text,
            property_id uuid NOT NULL,
            previous_state jsonb,
            resulting_state jsonb,
            correlation_id uuid NOT NULL,
            source text NOT NULL,
            outcome text NOT NULL,
            authorization_evidence jsonb,
            linked_source_event_id uuid,
            customer_id uuid,
            unit_id uuid,
            lease_id uuid,
            CONSTRAINT audit_events_source_allowed CHECK (
                source IN ('UI', 'API', 'SCHEDULED', 'ADMINISTRATIVE')
            ),
            CONSTRAINT audit_events_required_text_nonblank CHECK (
                length(btrim(action)) > 0
                AND length(btrim(entity_type)) > 0
                AND length(btrim(reason)) > 0
                AND length(btrim(outcome)) > 0
            ),
            CONSTRAINT audit_events_authorization_reference_nonblank CHECK (
                authorization_reference IS NULL
                OR length(btrim(authorization_reference)) > 0
            ),
            CONSTRAINT audit_events_snapshot_or_source_required CHECK (
                previous_state IS NOT NULL
                OR resulting_state IS NOT NULL
                OR linked_source_event_id IS NOT NULL
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX audit_events_property_history_idx
        ON app.audit_events (property_id, occurred_at DESC, id DESC)
        """
    )
    op.execute(
        "CREATE INDEX audit_events_customer_filter_idx "
        "ON app.audit_events (property_id, customer_id) WHERE customer_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX audit_events_unit_filter_idx "
        "ON app.audit_events (property_id, unit_id) WHERE unit_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX audit_events_lease_filter_idx "
        "ON app.audit_events (property_id, lease_id) WHERE lease_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE INDEX audit_events_entity_history_idx
        ON app.audit_events (entity_type, entity_id, occurred_at, id)
        """
    )
    op.execute(
        """
        CREATE INDEX audit_events_actor_history_idx
        ON app.audit_events (actor_id, occurred_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX audit_events_correlation_idx
        ON app.audit_events (correlation_id)
        """
    )
    op.execute(
        """
        CREATE INDEX audit_events_business_date_idx
        ON app.audit_events (business_date)
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit events are append-only' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        REVOKE ALL ON FUNCTION app.reject_audit_event_mutation() FROM PUBLIC
        """
    )
    op.execute(
        """
        CREATE TRIGGER reject_audit_event_update_or_delete
        BEFORE UPDATE OR DELETE ON app.audit_events
        FOR EACH ROW
        EXECUTE FUNCTION app.reject_audit_event_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER reject_audit_event_truncate
        BEFORE TRUNCATE ON app.audit_events
        FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_audit_event_mutation()
        """
    )
    op.execute(
        "ALTER TABLE app.audit_events ENABLE ALWAYS TRIGGER "
        "reject_audit_event_update_or_delete"
    )
    op.execute(
        "ALTER TABLE app.audit_events ENABLE ALWAYS TRIGGER "
        "reject_audit_event_truncate"
    )
    op.execute(
        "REVOKE ALL ON TABLE app.audit_events FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute("GRANT SELECT, INSERT ON TABLE app.audit_events TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback; audit history requires a reviewed forward fix."""
    raise RuntimeError("audit events migration is forward-only")
