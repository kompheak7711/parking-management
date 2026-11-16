"""UI v81 (B5, owner 07/11/2026): standard English names for four Ledger accounts.

The wording review the owner accepted on 07/11/2026 (docs/ui-audit/03_WORDING_REVIEW.md, owner
decision 6) renames only the English display names:

- 1100 "Customer debt · Invoices" -> "Accounts receivable · Invoices"
- 1110 "Customer debt · late-payment charges" -> "Accounts receivable · late-payment charges"
- 2210 "Money not used yet" -> "Unapplied payments"
- 3900 "Profit kept from past years" -> "Retained earnings"

Display only. Codes, types, control sources, Khmer names and every entry stay as they are. The
names live in two places: ``app.gl_chart_template`` (copied when a Property's ledger starts; its
update trigger is paused for this one change) and ``app.gl_accounts`` (each Property's chart,
where the guard allows a name change). A name the Property has already changed itself is kept.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270626_360"
down_revision: str | None = "20270716_391"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# code -> (old English name, new English name)
NAMES: dict[str, tuple[str, str]] = {
    "1100": ("Customer debt · Invoices", "Accounts receivable · Invoices"),
    "1110": (
        "Customer debt · late-payment charges",
        "Accounts receivable · late-payment charges",
    ),
    "2210": ("Money not used yet", "Unapplied payments"),
    "3900": ("Profit kept from past years", "Retained earnings"),
}


def _rename(table: str, old: str, new: str, code: str) -> None:
    op.execute(
        f"UPDATE app.{table} SET name_en = '{new}' WHERE code = '{code}' AND name_en = '{old}'"
    )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app.gl_chart_template "
        "DISABLE TRIGGER gl_chart_template_reject_update_or_delete"
    )
    for code, (old, new) in NAMES.items():
        _rename("gl_chart_template", old, new, code)
    op.execute(
        "ALTER TABLE app.gl_chart_template ENABLE TRIGGER gl_chart_template_reject_update_or_delete"
    )
    for code, (old, new) in NAMES.items():
        _rename("gl_accounts", old, new, code)


def downgrade() -> None:
    raise RuntimeError("The Ledger account names migration is forward-only")
