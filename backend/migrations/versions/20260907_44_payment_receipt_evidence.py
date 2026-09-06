"""Expose only original receipt facts, never private confirmation command identity."""

from alembic import op

revision = "20260907_44"
down_revision = "20260906_43"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a narrow read-only projection; historical rows are never rewritten."""
    op.execute("""
        CREATE VIEW app.payment_receipt_evidence WITH (security_barrier=true) AS
        SELECT payment.id AS payment_id, payment.property_id,
            command.response->>'received_at' AS received_at,
            command.response->>'evidence_reference' AS evidence_reference
        FROM app.payments payment
        LEFT JOIN app.payment_confirmation_commands command ON command.payment_id=payment.id;
        REVOKE ALL ON app.payment_receipt_evidence
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT SELECT ON app.payment_receipt_evidence TO prm_runtime,prm_financial;
    """)


def downgrade() -> None:
    raise RuntimeError("Payment receipt evidence is forward-only")
