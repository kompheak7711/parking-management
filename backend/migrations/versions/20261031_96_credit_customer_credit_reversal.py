# ruff: noqa: E501
"""Refuse the one-call reversal of a Credit released to another Customer (V1-056 sub-slice 8g).

BR-CREDIT-014, BR-CREDIT-008, BR-AUTH-010; owner answer to Q-2026-10-06-35 (approved tightening).

- A Customer Credit that a credit Adjustment released (app.invoice_credit_excess_releases) to a
  Customer who is not the payer of its source Payment belongs to that Customer, and any Refund of
  it goes to that Customer (BR-CREDIT-014). These are exactly the Credits the CREDIT_CUSTOMER
  Refund draft of sub-slice 8f pays: app.credit_customer_refund_basis(credit) IS NOT NULL.
- Until now only a Credit released from a moved (WRONG_UNIT_MOVE) allocation was refused (slice
  7, customer_credit_reversals_moved_payment). The one-call Credit reversal (credits.reverse,
  app.reverse_customer_credit) of a third-party Payment's adjustment Credit put the value back on
  the payer's Payment, where an ordinary Payment Refund draft could pay it to the payer.
- New BEFORE INSERT trigger customer_credit_reversals_other_customer refuses the reversal of every
  such Credit with the slice 7 SQLSTATE P4904 (CustomerCreditService reports it as a conflict).
  Its name sorts after the slice 7 trigger and before the Credit reversal checks
  (customer_credit_reversals_validate), as the slice 7 refusal does. The basis reads only rows
  that never change (the Credit, its Payment's payer, the append-only release), so it takes no lock.
- Such a Credit can still be applied to its Customer's obligations (credits.apply) or refunded to
  its Customer through a CREDIT_CUSTOMER Refund draft confirmed by financial.approve (8f).

Tightening: it refuses input accepted before. Earlier reversal rows are not touched, and the
replay of an earlier committed reversal writes no row, so it still replays.
"""

from alembic import op

revision = "20261031_96"
down_revision = "20261030_95"
branch_labels = None
depends_on = None

REFUSAL = "app.validate_credit_customer_credit_reversal()"


def upgrade() -> None:
    op.execute("""
        -- Q-2026-10-06-35: a Credit that a credit Adjustment released to a Customer other than the
        -- payer stays with that Customer; reversing it would put its value back on the payer's
        -- Payment.
        CREATE FUNCTION app.validate_credit_customer_credit_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF app.credit_customer_refund_basis(NEW.customer_credit_id) IS NOT NULL
            THEN RAISE EXCEPTION 'A Credit released to a Customer other than the payer stays with that Customer; apply it to that Customer''s obligations or refund it to that Customer'
                USING ERRCODE='P4904'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER customer_credit_reversals_other_customer BEFORE INSERT
            ON app.customer_credit_reversals FOR EACH ROW
            EXECUTE FUNCTION app.validate_credit_customer_credit_reversal();
    """)
    op.execute(
        f"REVOKE ALL ON FUNCTION {REFUSAL} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )


def downgrade() -> None:
    raise RuntimeError("Credit Customer Credit reversal migration is forward-only")
