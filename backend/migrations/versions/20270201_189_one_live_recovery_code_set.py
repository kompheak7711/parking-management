"""One live recovery-code set per account (login slice sub-slice L3c-2c-1).

DL-058, API-098, TEST-129, DB-AUTH-003. A signed-in person gets 10 recovery codes once after the
first sign-in code and replaces them by regeneration, which invalidates the prior set before it
writes the new one; a partial unique index makes a second live set of one account impossible, so
two parallel requests cannot leave two sets of codes that both work. A purely additive change.
"""

from alembic import op

revision = "20270201_189"
down_revision = "20270131_188"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Allow at most one recovery-code set that is not invalidated per account."""
    op.execute(
        """
        CREATE UNIQUE INDEX recovery_code_sets_one_live_per_actor
        ON app.recovery_code_sets (actor_id)
        WHERE invalidated_at IS NULL
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("one live recovery-code set migration is forward-only")
