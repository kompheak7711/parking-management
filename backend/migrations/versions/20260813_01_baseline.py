"""Add the smallest useful Phase 1C schema baseline."""

from alembic import op

revision = "20260813_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create an additive schema marker and least-privilege runtime grants."""
    op.execute("CREATE SCHEMA app AUTHORIZATION CURRENT_USER")
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute(
        """
        CREATE TABLE app.schema_baseline (
            baseline_key text PRIMARY KEY CHECK (length(btrim(baseline_key)) > 0),
            installed_at timestamptz NOT NULL DEFAULT statement_timestamp()
        )
        """
    )
    op.execute("INSERT INTO app.schema_baseline (baseline_key) VALUES ('phase-1c')")
    op.execute("GRANT USAGE ON SCHEMA app TO prm_runtime")
    op.execute("GRANT SELECT ON app.schema_baseline TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("Baseline migration is forward-only")