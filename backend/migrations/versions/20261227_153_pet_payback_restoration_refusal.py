# ruff: noqa: E501
"""A forgiven recovery charge is not restored while a forfeiture relies on it (V1-056 sub-slice 10e-2b-4b-2a).

BR-SETTLE-013, BR-DEP-022, DL-032, DL-053, BR-INV-044; DB-DEP-004, DB-REFUND-002; owner answer
(a) to Q-2026-10-17-126 point 1: restoring a forgiven recovery charge is refused while a
forfeiture that relied on the lower count is active. Staff first reverse that forfeiture with the
existing reversal, then restore the charge. The Customer must never owe money that the Property
also keeps.

- A recovery counts as returned money only while its charge stands (sub-slice 10e-2b-4b-1), so a
  forgiven recovery charge (a credit Adjustment, a CHARGE_REDUCTION or REFUND correction's
  Adjustment, a VOID) lowers the Pet Deposit's pay-back count, and a forfeiture recorded then may
  take more. A restoration of that charge is a DEBIT Adjustment of its line, an Adjustment
  reversal of a credit Adjustment of its line (the 10f-1 draft, the 10f-2 correction), or the same
  charge billed again and issued after a VOID: a DEBIT or a credit's reversal always, an issue only
  when another Invoice of the same obligation exists (a recovery's own charge is its obligation's
  first Invoice; review round 1, security: a structural rule, not a time rule).
- A forfeiture relied on the lower count when it was recorded at or after the charge's first
  issue, at a time when the charge stood lower than it stands after the restoration: its insert
  check read a count lowered by this charge's forgiveness. While such a forfeiture of the recovered
  Refund's Pet Deposit is not reversed, the restoration is refused (55000). A forfeiture recorded
  before the forgiveness never blocks; a forgiveness stays open.
- The check is a deferred constraint trigger; every restoring writer runs SET CONSTRAINTS ALL
  IMMEDIATE, so it runs inside that writer, which keeps its locks to commit. It first takes
  app.serialize_deposit_state of that Pet Deposit, the lock every forfeiture insert takes (the
  Deposit balance event trigger), then reads the forfeitures in a new statement. A forfeiture whose
  time is at or after the restoring transaction's start committed while that transaction ran, so
  its own check did not see the restoration: it counts as relying (fail closed).
- A forfeiture is timed by its statement's start, before it waits for the Deposit lock and reads
  the count, while a forgiveness takes no Deposit lock (review round 1, independent S1). So a
  forfeiture whose own insert finds a recovery charge of that Pet Deposit standing lower now than
  at the forfeiture's time (a forgiveness dated after it is already visible), or first issued after
  its time (a charge dated ahead of the clock; review round 2, security S1), is refused (40001,
  retry): its count may have read that change, which its time would not show.

New internal app.refuse_recovery_charge_restoration, app.validate_recovery_charge_restoration and
app.validate_forfeiture_recovery_standing (no grant), four deferred constraint triggers on
app.invoice_adjustments (DEBIT), app.invoice_adjustment_reversals and app.invoices (inserted as
issued, or issued later) and one AFTER INSERT trigger on app.deposit_dispositions. A fail-closed
tightening approved by the owner's answer; no table, column, grant or committed function changes.
"""

from alembic import op

revision = "20261227_153"
down_revision = "20261226_152"
branch_labels = None
depends_on = None

SQL = r"""
    -- Sub-slice 10e-2b-4b-2a (owner answer (a) to Q-2026-10-17-126): a restoration of the recovery
    -- charge billed for p_obligation is refused while a forfeiture of the recovered Refund's Pet
    -- Deposit that relied on the lower count is active.
    CREATE FUNCTION app.refuse_recovery_charge_restoration(p_obligation uuid)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_recovery uuid; v_first_issued timestamptz; v_deposit uuid;
        BEGIN
            SELECT recovery.id,refund.source_deposit_id,
                (SELECT min(invoice.issued_at) FROM app.invoice_lines line
                    JOIN app.invoices invoice ON invoice.id=line.invoice_id
                    WHERE line.authorized_obligation_id=p_obligation)
            INTO v_recovery,v_deposit,v_first_issued
            FROM app.refund_corrections recovery
            JOIN app.refunds refund ON refund.id=recovery.refund_id
            JOIN app.deposits deposit ON deposit.id=refund.source_deposit_id
            WHERE recovery.recovery_obligation_id=p_obligation
              AND recovery.correction_kind='RECOVERED_BY_CHARGE'
              AND deposit.deposit_type='PET';
            -- Only a Pet Deposit has a pay-back count.
            IF v_recovery IS NULL THEN RETURN; END IF;
            -- The lock every forfeiture insert takes (the Deposit balance event trigger); the
            -- forfeitures are then read in a new statement.
            PERFORM app.serialize_deposit_state(v_deposit);
            IF EXISTS(SELECT 1 FROM app.deposit_dispositions disposition
                WHERE disposition.deposit_id=v_deposit
                  -- Not before the charge existed (that forfeiture's count did not hold it).
                  AND disposition.occurred_at>=v_first_issued
                  AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal
                      WHERE reversal.deposit_disposition_id=disposition.id)
                  -- Recorded while the charge stood lower than it stands now, or committed
                  -- while this transaction ran (its own check could not see the restoration).
                  AND (disposition.occurred_at>=now()
                      OR app.refund_recovery_standing_at(v_recovery,disposition.occurred_at)
                          <app.refund_recovery_standing_at(v_recovery,'infinity')))
            THEN RAISE EXCEPTION 'A forfeiture recorded while this recovery charge was forgiven is still active; reverse the forfeiture first'
                USING ERRCODE='55000'; END IF;
        END $$;

    CREATE FUNCTION app.validate_recovery_charge_restoration()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_obligation uuid;
        BEGIN
            IF TG_TABLE_NAME='invoice_adjustments' THEN
                SELECT line.authorized_obligation_id INTO v_obligation
                FROM app.invoice_lines line WHERE line.id=NEW.invoice_line_id;
                PERFORM app.refuse_recovery_charge_restoration(v_obligation);
            ELSIF TG_TABLE_NAME='invoice_adjustment_reversals' THEN
                -- The reversal of a credit Adjustment restores what that credit forgave.
                SELECT line.authorized_obligation_id INTO v_obligation
                FROM app.invoice_adjustments adjustment
                JOIN app.invoice_lines line ON line.id=adjustment.invoice_line_id
                WHERE adjustment.id=NEW.invoice_adjustment_id AND adjustment.adjustment_type='CREDIT';
                PERFORM app.refuse_recovery_charge_restoration(v_obligation);
            ELSE
                -- The same charge billed again: another Invoice of the obligation exists (a
                -- recovery's own charge is its obligation's first Invoice).
                FOR v_obligation IN SELECT line.authorized_obligation_id FROM app.invoice_lines line
                    WHERE line.invoice_id=NEW.id AND line.authorized_obligation_id IS NOT NULL
                      AND EXISTS(SELECT 1 FROM app.invoice_lines other
                          WHERE other.authorized_obligation_id=line.authorized_obligation_id
                            AND other.invoice_id<>NEW.id)
                    ORDER BY line.id
                LOOP
                    PERFORM app.refuse_recovery_charge_restoration(v_obligation);
                END LOOP;
            END IF;
            RETURN NULL;
        END $$;

    -- Review round 1 (independent S1): a forfeiture's time is its statement's start, taken before
    -- it waits for the Deposit lock and reads the count, and a forgiveness takes no Deposit lock.
    -- A forgiveness of a recovery charge of this Pet Deposit dated after the forfeiture and already
    -- visible may have lowered the count it read, and a charge first issued after it was read too:
    -- refused, so the restoration check can trust the forfeiture's time.
    CREATE FUNCTION app.validate_forfeiture_recovery_standing()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF EXISTS(SELECT 1 FROM app.refund_corrections recovery
                JOIN app.refunds refund ON refund.id=recovery.refund_id
                JOIN app.deposits deposit ON deposit.id=refund.source_deposit_id
                WHERE refund.source_deposit_id=NEW.deposit_id AND deposit.deposit_type='PET'
                  AND recovery.correction_kind='RECOVERED_BY_CHARGE'
                  AND (app.refund_recovery_standing_at(recovery.id,NEW.occurred_at)
                          >app.refund_recovery_standing_at(recovery.id,'infinity')
                      -- Review round 2 (security S1): a charge first issued after the
                      -- forfeiture's time (dated ahead of the clock) was read by its count.
                      OR (SELECT min(invoice.issued_at) FROM app.invoice_lines line
                          JOIN app.invoices invoice ON invoice.id=line.invoice_id
                          WHERE line.authorized_obligation_id=recovery.recovery_obligation_id)
                          >NEW.occurred_at))
            THEN RAISE EXCEPTION 'A recovery charge of this Pet Deposit changed after this forfeiture''s time; record it again'
                USING ERRCODE='40001'; END IF;
            RETURN NULL;
        END $$;

    CREATE TRIGGER deposit_dispositions_recovery_standing AFTER INSERT
        ON app.deposit_dispositions FOR EACH ROW
        WHEN (NEW.governing_lease_id IS NOT NULL)
        EXECUTE FUNCTION app.validate_forfeiture_recovery_standing();
    CREATE CONSTRAINT TRIGGER invoice_adjustments_recovery_restoration AFTER INSERT
        ON app.invoice_adjustments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        WHEN (NEW.adjustment_type='DEBIT')
        EXECUTE FUNCTION app.validate_recovery_charge_restoration();
    CREATE CONSTRAINT TRIGGER invoice_adjustment_reversals_recovery_restoration AFTER INSERT
        ON app.invoice_adjustment_reversals DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION app.validate_recovery_charge_restoration();
    CREATE CONSTRAINT TRIGGER invoices_recovery_restoration_insert AFTER INSERT
        ON app.invoices DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        WHEN (NEW.issued_at IS NOT NULL)
        EXECUTE FUNCTION app.validate_recovery_charge_restoration();
    CREATE CONSTRAINT TRIGGER invoices_recovery_restoration_issue AFTER UPDATE OF issued_at
        ON app.invoices DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        WHEN (OLD.issued_at IS NULL AND NEW.issued_at IS NOT NULL)
        EXECUTE FUNCTION app.validate_recovery_charge_restoration();
"""

INTERNAL = (
    "app.refuse_recovery_charge_restoration(uuid)",
    "app.validate_recovery_charge_restoration()",
    "app.validate_forfeiture_recovery_standing()",
)


def upgrade() -> None:
    op.execute(SQL)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Pet pay-back restoration refusal migration is forward-only")
