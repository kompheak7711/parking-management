"""Only the audited Settings access functions for the runtime role (login slice sub-slice L2b-1).

DL-081 (Q-2026-10-21-167 (a), owner, 2026-10-22), SEC-014, SEC-075, DB-AUTH-008: the runtime
role may no longer execute `app.give_settings_access` and `app.remove_settings_access`, which
write no audit event. It gives and removes Settings access only through
`app.admin_give_settings_access` and `app.admin_remove_settings_access` (sub-slice L2a), which
call them as their owner and write the audit event in the same transaction. A tightening
approved by the owner; nothing else changes.
"""

from alembic import op

revision = "20270125_182"
down_revision = "20270124_181"
branch_labels = None
depends_on = None

UNAUDITED = (
    "app.give_settings_access(uuid,uuid,text)",
    "app.remove_settings_access(uuid,uuid,text)",
)


def upgrade() -> None:
    """Take away the runtime role's EXECUTE on the two unaudited functions."""
    for function in UNAUDITED:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {function} FROM prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("settings access runtime revoke migration is forward-only")
