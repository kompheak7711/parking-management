"""Telegram bots step 4: the Staff bot line starts after HR (no change to the database).

The Staff bot needs both the Telegram tables (migrations 20270430_281 to 20270527_289) and the
HR tables and bot functions (20270430_300 to 20270505_305). HR now follows the Telegram head, so
this revision follows the HR head and every later Staff bot migration follows it.
Technical choice by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

revision: str = "20270619_330"
down_revision: str | Sequence[str] | None = "20270505_305"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to change: the Staff bot line starts here."""


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
