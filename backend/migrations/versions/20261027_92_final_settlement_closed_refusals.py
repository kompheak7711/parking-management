# ruff: noqa: E501
"""Refusals after a Final Settlement closes (V1-056 sub-slice 8e-1).

Owner answer 7 to Q-2026-10-05-20 (approved tightening; BR-SETTLE-012, BR-SETTLE-013): once a
Final Settlement is closed, one-call changes to its obligations are refused until the slice 10
correction drafts exist: VOID, Adjustments (also through the hand-back and unpaid-Initial
resolutions) and their reversals, Late-payment Decisions and Charges and Late-payment Charge
corrections on the Lease's Invoices, and new charges on the Lease (a new Invoice with the Lease,
which covers Rent, Utility, final Utility, catch-up Utility and Invoice drafts naming any Signer;
an Invoice draft corrected onto a charge of the Lease or issued with the Lease; and a new
one-time, Damage or cleaning charge with the Lease). Payments, allocations, Credit applications
and their ordinary reversals stay open, so the Customer can still pay the debt.

- app.refuse_closed_final_settlement_change runs BEFORE INSERT on the eight tables those writers
  use, and BEFORE UPDATE OF lease_id, status on app.invoices when a row gets a Lease or a DRAFT
  with a Lease is issued (review round 1, blocker B1: app.correct_invoice_draft and
  app.issue_invoice change an existing row). A Lease without a Final Settlement takes no lock
  and nothing changes. Otherwise it locks the target Invoice (the lock the writers' own source
  triggers take) and then the Settlement row FOR SHARE, so it waits for a running confirm (8e-3)
  and then sees the closure; a confirm that starts later locks the Lease's Invoices first and
  then sees the change. The refusal is SQLSTATE P5S01; each affected service maps it to a
  conflict. A DRAFT may still become VOID by UPDATE, but its VOID event is refused like every
  other VOID (owner answer 3 to Q-2026-10-06-33).
- Its trigger names start with "a0_", so it runs before the earlier refusal of an obligation a
  Deposit application paid (8a-1) and the closed Settlement is the reason given.
- Owner answer 1 to Q-2026-10-06-33: a scheduled Rent or Utility run records a Lease whose
  Settlement is closed as SKIPPED with the diagnostic FINAL_SETTLEMENT_CLOSED, so the run can
  succeed and the VOID of its other Invoices is never held back; the run item's allowed codes
  and the missing-source check accept the new code (relaxing), and the two run item functions
  check it before they bill.
- No closed Settlement exists before the confirm (8e-3), so nothing changes for existing data.

Additive or relaxing: one trigger function and nine triggers, one more allowed run diagnostic,
and the two run item functions patched in place.
"""

from alembic import op
from sqlalchemy import text

revision = "20261027_92"
down_revision = "20261026_91"
branch_labels = None
depends_on = None

FUNCTION = "app.refuse_closed_final_settlement_change()"
TABLES = (
    "invoice_void_events",
    "invoice_adjustments",
    "invoice_adjustment_reversals",
    "late_payment_decisions",
    "late_payment_charges",
    "late_payment_charge_corrections",
    "invoices",
    "authorized_nonrecurring_obligations",
)
MISSING_SOURCES = "app.billing_run_has_missing_eligible_sources(uuid,integer)"
RENT_ITEM = "app.record_scheduled_rent_item(uuid,uuid,uuid,uuid,text,uuid,text,uuid,timestamptz)"
UTILITY_ITEM = "app.record_scheduled_utility_item(uuid,uuid,text,uuid,uuid,text,uuid,timestamptz)"

MISSING_BEFORE = "'SOURCE_NO_LONGER_ELIGIBLE','ZERO_AMOUNT_NO_OBLIGATION','NOT_MOVED_IN','PROPERTY_BORNE_CONSUMPTION'"
MISSING_AFTER = (
    "'SOURCE_NO_LONGER_ELIGIBLE','ZERO_AMOUNT_NO_OBLIGATION','NOT_MOVED_IN',"
    "'PROPERTY_BORNE_CONSUMPTION','FINAL_SETTLEMENT_CLOSED'"
)
RENT_DECLARE_BEFORE = "        DECLARE v_sqlstate text;\n"
RENT_DECLARE_AFTER = "        DECLARE v_sqlstate text; v_settlement_closed_at timestamptz;\n"
RENT_BILL_BEFORE = (
    "            BEGIN\n                v_result:=app.generate_rent_service_invoice(\n"
)
RENT_BILL_AFTER = (
    "            -- A Lease whose Final Settlement is closed is skipped, so the run can succeed\n"
    "            -- (owner answer 1 to Q-2026-10-06-33; V1-056 sub-slice 8e-1). FOR SHARE waits\n"
    "            -- for a running closure.\n"
    "            SELECT settlement.closed_at INTO v_settlement_closed_at FROM app.final_settlements settlement\n"
    "            WHERE settlement.lease_id=p_source_id FOR SHARE;\n"
    "            IF v_settlement_closed_at IS NOT NULL THEN\n"
    "                INSERT INTO app.billing_run_items(\n"
    "                    id,billing_run_id,billing_run_attempt_id,source_kind,source_id,\n"
    "                    source_period_start,source_period_end,outcome,diagnostic_code,recorded_at\n"
    "                ) VALUES (v_item_id,p_run_id,p_attempt_id,'LEASE_PERIOD',p_source_id,\n"
    "                    v_run.period_start,v_run.period_end,'SKIPPED','FINAL_SETTLEMENT_CLOSED',\n"
    "                    clock_timestamp());\n"
    "                RETURN 'SKIPPED';\n"
    "            END IF;\n" + RENT_BILL_BEFORE
)
UTILITY_DECLARE_BEFORE = "DECLARE v_resp_outcome text;"
UTILITY_DECLARE_AFTER = "DECLARE v_resp_outcome text; v_settlement_closed_at timestamptz;"
UTILITY_RESPONSIBLE_BEFORE = (
    "                IF v_resp_outcome IS DISTINCT FROM 'RESPONSIBLE' THEN\n"
    "                    RAISE EXCEPTION 'Utility responsibility evidence was not found'\n"
    "                        USING ERRCODE='P0002';\n"
    "                END IF;"
)
UTILITY_RESPONSIBLE_AFTER = (
    UTILITY_RESPONSIBLE_BEFORE + "\n"
    "                -- The responsible Lease's Final Settlement is closed: skipped, so the run can\n"
    "                -- succeed (owner answer 1 to Q-2026-10-06-33; V1-056 sub-slice 8e-1).\n"
    "                SELECT settlement.closed_at INTO v_settlement_closed_at\n"
    "                FROM app.final_settlements settlement WHERE settlement.lease_id=v_lease_id FOR SHARE;\n"
    "                IF v_settlement_closed_at IS NOT NULL THEN\n"
    "                    INSERT INTO app.billing_run_items(\n"
    "                        id,billing_run_id,billing_run_attempt_id,source_kind,source_id,\n"
    "                        source_period_start,source_period_end,outcome,diagnostic_code,recorded_at\n"
    "                    ) VALUES (v_item_id,p_run_id,p_attempt_id,p_source_kind,p_source_id,\n"
    "                        v_run.period_start,v_run.period_end,'SKIPPED','FINAL_SETTLEMENT_CLOSED',\n"
    "                        clock_timestamp());\n"
    "                    RETURN 'SKIPPED';\n"
    "                END IF;"
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Closed Final Settlement run contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute("""
        -- Owner answer 7 to Q-2026-10-05-20: after closure a Final Settlement's obligations change
        -- only through a post-settlement correction (BR-SETTLE-013; slice 10).
        CREATE FUNCTION app.refuse_closed_final_settlement_change()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_invoice uuid; v_lease uuid; v_closed timestamptz;
        BEGIN
            -- Separate branches: each table's row has only its own columns. On app.invoices the
            -- row's own Lease decides, for an INSERT and for the guarded UPDATE alike; the
            -- UPDATE already holds the Invoice row.
            IF TG_TABLE_NAME IN ('invoices','authorized_nonrecurring_obligations') THEN
                v_lease:=NEW.lease_id;
            ELSIF TG_TABLE_NAME IN ('invoice_void_events','invoice_adjustments') THEN
                v_invoice:=NEW.invoice_id;
            ELSIF TG_TABLE_NAME='invoice_adjustment_reversals' THEN
                SELECT adjustment.invoice_id INTO v_invoice FROM app.invoice_adjustments adjustment
                WHERE adjustment.id=NEW.invoice_adjustment_id;
            ELSIF TG_TABLE_NAME IN ('late_payment_decisions','late_payment_charges') THEN
                v_invoice:=NEW.source_invoice_id;
            ELSIF TG_TABLE_NAME='late_payment_charge_corrections' THEN
                SELECT charge.source_invoice_id INTO v_invoice FROM app.late_payment_charges charge
                WHERE charge.id=NEW.late_payment_charge_id;
            ELSE
                RAISE EXCEPTION 'Closed Final Settlement guard is attached to an unknown table'
                    USING ERRCODE='P0001';
            END IF;
            IF v_invoice IS NOT NULL THEN
                SELECT invoice.lease_id INTO v_lease FROM app.invoices invoice WHERE invoice.id=v_invoice;
            END IF;
            -- A Lease without a Final Settlement: no lock, no change.
            IF v_lease IS NULL OR NOT EXISTS(SELECT 1 FROM app.final_settlements settlement
                WHERE settlement.lease_id=v_lease)
            THEN RETURN NEW; END IF;
            -- Lock order of the confirm (8e-3): the Lease's Invoices, then the Settlement row.
            IF v_invoice IS NOT NULL THEN
                PERFORM 1 FROM app.invoices WHERE id=v_invoice FOR UPDATE;
            END IF;
            SELECT settlement.closed_at INTO v_closed FROM app.final_settlements settlement
            WHERE settlement.lease_id=v_lease FOR SHARE;
            IF v_closed IS NOT NULL THEN
                RAISE EXCEPTION 'A closed Final Settlement changes only through a post-settlement correction'
                    USING ERRCODE='P5S01';
            END IF;
            RETURN NEW;
        END $$;
    """)
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER a0_{table}_final_settlement_closed BEFORE INSERT ON app.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION {FUNCTION}"
        )
    # Review round 1, blocker B1: a draft corrected onto a charge of the Lease, or a DRAFT with the
    # Lease issued, changes an existing row. Payment, allocation and Credit status updates change
    # neither the Lease nor a DRAFT's status, so they are not guarded.
    op.execute(f"""
        CREATE TRIGGER a0_invoices_final_settlement_closed_update
            BEFORE UPDATE OF lease_id, status ON app.invoices FOR EACH ROW
            WHEN (NEW.lease_id IS NOT NULL AND (OLD.lease_id IS DISTINCT FROM NEW.lease_id
                OR (OLD.status='DRAFT' AND NEW.status NOT IN ('DRAFT','VOID'))))
            EXECUTE FUNCTION {FUNCTION}
    """)
    op.execute(
        f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    # Owner answer 1 to Q-2026-10-06-33: a run skips a Lease whose Settlement is closed.
    op.execute("""
        ALTER TABLE app.billing_run_items
            DROP CONSTRAINT billing_run_items_outcome_shape,
            ADD CONSTRAINT billing_run_items_outcome_shape CHECK (
                (outcome='GENERATED' AND invoice_id IS NOT NULL AND diagnostic_code IS NULL)
                OR (outcome='SKIPPED' AND (
                    (invoice_id IS NOT NULL
                        AND diagnostic_code='ACTIVE_INVOICE_ALREADY_EXISTS')
                    OR (invoice_id IS NULL AND diagnostic_code IN (
                        'SOURCE_NO_LONGER_ELIGIBLE',
                        'PENDING_FUTURE_ACTUAL_BASIS',
                        'ZERO_AMOUNT_NO_OBLIGATION',
                        'NOT_MOVED_IN',
                        'PROPERTY_BORNE_CONSUMPTION',
                        'FINAL_SETTLEMENT_CLOSED'
                    ))
                ))
                OR (outcome IN ('CONFLICT','ERROR') AND invoice_id IS NULL
                    AND diagnostic_code IS NOT NULL
                    AND length(btrim(diagnostic_code))>0
                    AND length(diagnostic_code)<=100
                    AND diagnostic_code=btrim(diagnostic_code))
            );
    """)
    _patch(MISSING_SOURCES, ((MISSING_BEFORE, MISSING_AFTER),))
    _patch(
        RENT_ITEM,
        ((RENT_DECLARE_BEFORE, RENT_DECLARE_AFTER), (RENT_BILL_BEFORE, RENT_BILL_AFTER)),
    )
    _patch(
        UTILITY_ITEM,
        (
            (UTILITY_DECLARE_BEFORE, UTILITY_DECLARE_AFTER),
            (UTILITY_RESPONSIBLE_BEFORE, UTILITY_RESPONSIBLE_AFTER),
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Closed Final Settlement refusal migration is forward-only")
