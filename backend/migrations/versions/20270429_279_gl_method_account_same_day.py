"""General Ledger: a method's ledger account can be changed again on the same day.

Owner test 04/11/2026: the Refund method Bank transfer was set to Cash on hand (USD) by mistake
and could not be fixed, because a method kept one account per start day. Owner card 12:12
"Yes, the newest save wins": a second save from the same day replaces the first for that day.
Both rows stay (the table is append-only), so the history shows every change.

- ``app.gl_method_accounts`` drops its two UNIQUE (method, effective_from) keys; plain indexes
  keep the look-ups fast.
- ``app.gl_app_record_events`` picks the newest save of the day (effective_from, then
  created_at); ``app.gl_method_list`` (migration ``20270428_278``) already does.

Forward-only: putting the keys back would fail once a day has two saves.
"""

import re
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270429_279"
down_revision: str | None = "20270428_278"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENTS = "app.gl_app_record_events(uuid, date, date)"
OLDEST_FIRST = "ORDER BY map.effective_from DESC LIMIT 1"
NEWEST_SAVE = "ORDER BY map.effective_from DESC, map.created_at DESC LIMIT 1"


def _literal_colons(sql: str) -> str:
    """Keep ``'invoice:...:issue'`` text from reading as a SQLAlchemy bind parameter."""
    return re.sub(r"(?<![:\w\\]):(?=\w)", r"\\:", sql)


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.gl_method_accounts
            DROP CONSTRAINT gl_method_accounts_payment_key,
            DROP CONSTRAINT gl_method_accounts_refund_key;
        CREATE INDEX gl_method_accounts_payment_idx
            ON app.gl_method_accounts (payment_method_id, effective_from, created_at);
        CREATE INDEX gl_method_accounts_refund_idx
            ON app.gl_method_accounts (refund_method_id, effective_from, created_at);
        """
    )
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": EVENTS},
        )
        .scalar_one()
    )
    # One look-up for Payment Methods, one for Refund methods.
    if definition.count(OLDEST_FIRST) != 2:
        raise RuntimeError(f"The method account look-up changed: {EVENTS}")
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(_literal_colons(definition.replace(OLDEST_FIRST, NEWEST_SAVE)))


def downgrade() -> None:
    raise RuntimeError("The same-day method account migration is forward-only")
