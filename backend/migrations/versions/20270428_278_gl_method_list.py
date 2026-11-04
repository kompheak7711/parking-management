# ruff: noqa: E501
"""General Ledger: the runtime login reads the methods for Needs check and the write-offs.

Owner test 04/11/2026: Ledger > Needs check said "This list could not be read just now". The
page also lists every Payment Method and Refund method with the ledger account it posts to, and
the runtime login may not read ``app.refund_methods`` (migration ``20261013_78`` keeps that table
behind its functions), so the read failed for every Property.

- ``app.gl_method_list(property, day)``: every Payment Method and Refund method with the ledger
  account it posts to on the day (none = its records wait in Needs check) and the day that
  account starts. Read only; the route has checked ``ledger.read``.
- ``app.gl_write_off_settlement(settlement correction)``: the Final Settlement a write-off's
  Settlement correction belongs to. The write-off list read ``app.settlement_corrections``,
  which the runtime login may not read either (found by the same check; no screen shows that
  list yet).

Technical choice by Claude under the owner's 2026-10-23 22:30 rule.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270428_278"
down_revision: str | None = "20270427_277"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = ("app.gl_method_list(uuid, date)", "app.gl_write_off_settlement(uuid)")


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION app.gl_method_list(p_property uuid, p_day date)
        RETURNS TABLE (kind text, method_id uuid, code text, name text, account_code text,
            account_name text, effective_from date)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT method.kind, method.id, method.code, method.name, account.code,
                account.name_en, mapped.effective_from
            FROM (
                SELECT 'PAYMENT' AS kind, payment.id, payment.code,
                    payment.display_name AS name
                FROM app.payment_methods AS payment
                UNION ALL
                SELECT 'REFUND', refund.id, refund.code, refund.display_name
                FROM app.refund_methods AS refund
            ) AS method
            LEFT JOIN LATERAL (
                SELECT map.account_id, map.effective_from FROM app.gl_method_accounts AS map
                WHERE map.property_id = p_property AND map.effective_from <= p_day
                  AND CASE method.kind WHEN 'PAYMENT' THEN map.payment_method_id
                      ELSE map.refund_method_id END = method.id
                ORDER BY map.effective_from DESC, map.created_at DESC LIMIT 1
            ) AS mapped ON true
            LEFT JOIN app.gl_accounts AS account ON account.id = mapped.account_id
            ORDER BY method.kind, method.code
        $$;

        CREATE FUNCTION app.gl_write_off_settlement(p_correction uuid)
        RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT correction.final_settlement_id FROM app.settlement_corrections AS correction
            WHERE correction.id = p_correction
        $$;
        """
    )
    for function in FUNCTIONS:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC; "
            f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime"
        )


def downgrade() -> None:
    """Reads only, so removing them loses nothing."""
    for function in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION {function}")
