# ruff: noqa: E501
"""Database review fixes of 7 Nov 2026, DL-202 (E): the database checks the right ledger.accounts.manage when a method's ledger account is set.

Owner 8 Nov 2026 04:39: "Add the gl_set_method_account inside rights check (ledger.accounts.manage),
with its test." The review of 7 Nov 2026 found that only the API checked the right before calling
``app.gl_set_method_account``; the function itself wrote the row for any actor. Every other ledger
change checks its right inside the database with ``app.gl_require`` (SQLSTATE 42501, "This needs
the right ..."), so this one does too.

The function is replaced with one change: its first statement is
``PERFORM app.gl_require(p_actor, p_property, 'ledger.accounts.manage')``. A call without the
right writes no account mapping and no audit event. CREATE OR REPLACE keeps the function's
identity, owner and grants (EXECUTE to prm_runtime only). Nothing else changes.

Forward-only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270708_373"
down_revision: str | None = "20270707_372"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = r"""
-- The Owner sets the ledger account of a Payment or Refund method (from a date). The right is
-- checked here, inside the database, not only by the API (DL-202 (E)).
CREATE OR REPLACE FUNCTION app.gl_set_method_account(p_property uuid, p_payment_method uuid,
    p_refund_method uuid, p_account_code text, p_effective_from date, p_actor uuid,
    p_correlation uuid, p_riel_account_code text DEFAULT NULL)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_account app.gl_accounts%ROWTYPE;
    v_riel app.gl_accounts%ROWTYPE;
    v_id uuid := gen_random_uuid();
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.accounts.manage');
    IF (p_payment_method IS NULL) = (p_refund_method IS NULL) THEN
        RAISE EXCEPTION 'Name one Payment Method or one Refund method' USING ERRCODE = '22023';
    END IF;
    SELECT account.* INTO v_account FROM app.gl_accounts AS account
    WHERE account.property_id = p_property AND account.code = p_account_code;
    IF NOT FOUND OR v_account.cash_kind IS NULL OR NOT v_account.is_active THEN
        RAISE EXCEPTION 'A method goes to an active cash or bank account' USING ERRCODE = '22023';
    END IF;
    IF v_account.cash_kind = 'BANK_KHR' AND p_refund_method IS NULL THEN
        RAISE EXCEPTION 'Account % keeps riel: choose it as the riel account', v_account.code
            USING ERRCODE = '22023';
    END IF;
    IF p_riel_account_code IS NOT NULL THEN
        IF p_refund_method IS NOT NULL THEN
            RAISE EXCEPTION 'Refunds are paid in dollars, so a Refund method has no riel account'
                USING ERRCODE = '22023';
        END IF;
        SELECT account.* INTO v_riel FROM app.gl_accounts AS account
        WHERE account.property_id = p_property AND account.code = p_riel_account_code;
        IF NOT FOUND OR coalesce(v_riel.cash_kind, '') NOT IN ('CASH_KHR', 'BANK_KHR')
            OR NOT v_riel.is_active THEN
            RAISE EXCEPTION 'The riel account is an active riel cash or riel bank account'
                USING ERRCODE = '22023';
        END IF;
    END IF;
    INSERT INTO app.gl_method_accounts (id, property_id, payment_method_id, refund_method_id,
        account_id, riel_account_id, effective_from, created_by)
    VALUES (v_id, p_property, p_payment_method, p_refund_method, v_account.id, v_riel.id,
        p_effective_from, p_actor);
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.method_account.set', 'gl_method_account',
        v_id, 'Ledger account of a payment or refund method', p_correlation,
        jsonb_build_object('payment_method_id', p_payment_method,
            'refund_method_id', p_refund_method, 'account', p_account_code,
            'riel_account', p_riel_account_code, 'effective_from', p_effective_from));
    RETURN v_id;
END $$;
"""


def upgrade() -> None:
    op.execute(FUNCTION)


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
