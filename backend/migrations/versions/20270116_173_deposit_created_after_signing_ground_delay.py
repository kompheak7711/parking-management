# ruff: noqa: E501
"""A Security Deposit created after signing counts for the unpaid-Initial ground only five days after its creation (V1-056 sub-slice 10i-4a).

BR-LEASE-005, BR-DEP-004, DL-066; owner answer (a) to Q-2026-10-20-148: the first amount of a
Security Deposit created after the Lease was signed (every walk-in Security Deposit) counts for the
unpaid-Initial termination ground only on a termination business date after its creation date plus
five days (Asia/Phnom_Penh business dates, the 10i-2 rule for increases). A Reservation's Deposit,
created before signing, keeps today's rule.

Whole-body CREATE OR REPLACE of the internal app.deposit_ground_required_total_at(deposit, as_of)
(its only reader is the ground since 10i-2): before its creation date plus five days such a
Deposit's first amount reads 0; the adjustments keep the 10i-2 rule. Only a Deposit with a
Reservation and a creation time at or before the Lease's signing time counts at once; a Deposit
with no Reservation (a walk-in Deposit, also one whose create statement started before a signing
that committed while it waited) and a Deposit whose Lease has no signing time always wait their five
days (review round 1, security; fails closed). Same signature, settings and definer flag;
CREATE OR REPLACE keeps the owner and the revoked EXECUTE. No table, column, trigger, constraint or
grant change.
"""

from alembic import op

revision = "20270116_173"
down_revision = "20270115_172"
branch_labels = None
depends_on = None

SQL = """
    -- Sub-slice 10i-2 (owner answer (b) to Q-2026-10-19-138): the required total the BR-LEASE-005
    -- ground reads; an increase counts only after its business date plus five days. Sub-slice
    -- 10i-4a (owner answer (a) to Q-2026-10-20-148): the first amount of a Deposit created after
    -- the Lease's signing counts only after its creation business date plus five days.
    CREATE OR REPLACE FUNCTION app.deposit_ground_required_total_at(p_deposit uuid,p_as_of timestamptz)
    RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        -- Only a Reservation's Deposit created by the signing time counts at once: a walk-in
        -- Deposit's create statement can start before a signing that commits while it waits, so
        -- a Deposit with no Reservation always waits its five days (review round 1, security).
        SELECT ((CASE WHEN (deposit.reservation_id IS NOT NULL AND deposit.created_at<=lease.signed_at)
                OR timezone('Asia/Phnom_Penh',deposit.created_at)::date+5
                    <timezone('Asia/Phnom_Penh',p_as_of)::date
            THEN deposit.required_usd_cents ELSE 0 END) + COALESCE((
            SELECT sum(CASE adjustment.adjustment_type WHEN 'INCREASE'
                THEN adjustment.amount_usd_cents ELSE -adjustment.amount_usd_cents END)
            FROM app.deposit_required_amount_adjustments AS adjustment
            WHERE adjustment.deposit_id=deposit.id AND adjustment.occurred_at<=p_as_of
              AND (adjustment.adjustment_type='DECREASE'
                OR timezone('Asia/Phnom_Penh',adjustment.occurred_at)::date+5
                    <timezone('Asia/Phnom_Penh',p_as_of)::date)
        ),0))::bigint
        FROM app.deposits AS deposit
        LEFT JOIN app.leases AS lease ON lease.id=deposit.lease_id
        WHERE deposit.id=p_deposit AND p_as_of IS NOT NULL
    $$;
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    raise RuntimeError("Deposit created after signing ground delay migration is forward-only")
