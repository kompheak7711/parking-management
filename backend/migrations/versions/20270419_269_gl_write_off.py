# ruff: noqa: E501
"""General Ledger write-off of Customer debt and Refund correction posting (phase 6 step 4, part 3).

Owner decisions: DESIGN.md gap G6 (round 25): Write off is on an unpaid Invoice after the Final
Settlement is closed, Owner only, with a reason; the entry is 6160 debit and 1110 credit for a
late-payment charge, 1100 credit for everything else; it is not a payment. The approved database
plan (phase 5, Q5): a write-off is a V1 CHARGE_REDUCTION correction marked in
``app.gl_write_offs``, and automatic posting sends it to 6160.

- ``app.gl_write_off`` (``ledger.write_off``) records the charge reduction draft and confirms it
  in one step, as the V1 Final Settlement corrections do (they check the closed Settlement, the
  unpaid rest and the Customer), then marks the correction as a write-off, in one transaction.
- Automatic posting: an Invoice adjustment or a Late-payment charge correction that belongs to a
  written-off correction posts against 6160 instead of income. A Rent line billed in advance
  still moves in full from 2050 to income in its month; the write-off takes it off 1100.
- Refund corrections post by themselves (owner's cards of 03/11/2026 13:05 and 13:10), no longer
  waiting in "Needs check" for an adjusting entry: money given back (VALUE_CORRECTION) debits the
  Refund method's account and credits the Refund's source (Deposit 2100 or 2110, Customer Credit
  2200, money not used yet 2210); its reversal does the opposite; a Refund recovered by a charge
  (RECOVERED_BY_CHARGE) credits the source against 4080, because the recovery Invoice itself
  posts 1100 against 4080.
"""

import importlib.util
import re
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "20270419_269"
down_revision: str | None = "20270418_268"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WRITE_OFF_SIGNATURE = "app.gl_write_off(uuid, uuid, uuid, jsonb, text, uuid)"

WRITE_OFF = r"""
CREATE FUNCTION app.gl_write_off(p_property uuid, p_actor uuid, p_settlement uuid,
    p_target jsonb, p_reason text, p_correlation uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_draft uuid := gen_random_uuid();
    v_late boolean;
    v_correction uuid;
    v_invoice uuid;
    v_amount bigint;
    v_id uuid := gen_random_uuid();
BEGIN
    PERFORM app.gl_require(p_actor, p_property, 'ledger.write_off');
    IF p_reason IS NULL OR btrim(p_reason) = '' OR length(btrim(p_reason)) > 500 THEN
        RAISE EXCEPTION 'A write-off needs a reason of up to 500 characters' USING ERRCODE = '22023';
    END IF;
    IF p_settlement IS NULL OR jsonb_typeof(p_target) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'Choose the Final Settlement and the Invoice line or Late-payment charge to write off'
            USING ERRCODE = '22023';
    END IF;
    v_late := p_target ? 'late_payment_charge_id';
    IF v_late THEN
        PERFORM app.record_settlement_late_charge_reduction_draft(p_property, p_actor, v_draft,
            p_settlement, p_target, btrim(p_reason), 'final_settlements.prepare');
        PERFORM app.confirm_settlement_late_charge_reduction(p_property, p_actor, v_draft,
            'financial.approve');
    ELSE
        PERFORM app.record_settlement_charge_reduction_draft(p_property, p_actor, v_draft,
            p_settlement, p_target, btrim(p_reason), 'final_settlements.prepare');
        PERFORM app.confirm_settlement_charge_reduction(p_property, p_actor, v_draft,
            'financial.approve');
    END IF;
    SELECT correction.id INTO STRICT v_correction FROM app.settlement_corrections AS correction
    WHERE correction.correlation_id = v_draft;
    IF v_late THEN
        SELECT charge.source_invoice_id, k.amount_usd_cents INTO STRICT v_invoice, v_amount
        FROM app.settlement_correction_effects AS effect
        JOIN app.late_payment_charge_corrections AS k
            ON k.id = effect.late_payment_charge_correction_id
        JOIN app.late_payment_charges AS charge ON charge.id = k.late_payment_charge_id
        WHERE effect.settlement_correction_id = v_correction;
    ELSE
        SELECT adjustment.invoice_id, adjustment.amount_usd_cents INTO STRICT v_invoice, v_amount
        FROM app.settlement_correction_effects AS effect
        JOIN app.invoice_adjustments AS adjustment ON adjustment.id = effect.invoice_adjustment_id
        WHERE effect.settlement_correction_id = v_correction;
    END IF;
    INSERT INTO app.gl_write_offs (id, property_id, settlement_correction_id, invoice_id,
        amount_cents, reason, approved_by, created_by)
    VALUES (v_id, p_property, v_correction, v_invoice, v_amount, btrim(p_reason), p_actor, p_actor);
    PERFORM app.gl_audit(p_property, p_actor, 'ledger.write_off', 'gl_write_off', v_id,
        btrim(p_reason), p_correlation, jsonb_build_object('invoice_id', v_invoice,
            'amount_cents', v_amount, 'late_payment_charge', v_late,
            'settlement_correction_id', v_correction));
    RETURN v_id;
END $$;
"""

# The automatic posting of migration 20270415_265, with written-off corrections sent to 6160.
WRITTEN_OFF_ADJUSTMENT = (
    "EXISTS (SELECT 1 FROM app.settlement_correction_effects AS effect "
    "JOIN app.gl_write_offs AS written ON written.settlement_correction_id = "
    "effect.settlement_correction_id WHERE effect.invoice_adjustment_id = {adjustment})"
)
WRITTEN_OFF_LATE = (
    "EXISTS (SELECT 1 FROM app.settlement_correction_effects AS effect "
    "JOIN app.gl_write_offs AS written ON written.settlement_correction_id = "
    "effect.settlement_correction_id WHERE effect.late_payment_charge_correction_id = k.id)"
)
EVENT_CHANGES = (
    # The adjustment list says which adjustments are write-offs.
    (
        """                WHEN 'UTILITIES' THEN '4030' WHEN 'MISCELLANEOUS_CHARGES' THEN '4080' END) AS other_code
    FROM app.invoice_adjustments AS a""",
        """                WHEN 'UTILITIES' THEN '4030' WHEN 'MISCELLANEOUS_CHARGES' THEN '4080' END) AS other_code,
        """
        + WRITTEN_OFF_ADJUSTMENT.format(adjustment="a.id")
        + """ AS written_off
    FROM app.invoice_adjustments AS a""",
    ),
    # A Rent line moves from 2050 in full when a write-off took part of it off 1100.
    (
        """            WHERE a.invoice_line_id = l.line_id
              AND timezone(zone.tz, a.occurred_at)::date < l.rent_month""",
        """            WHERE a.invoice_line_id = l.line_id
              AND timezone(zone.tz, a.occurred_at)::date < l.rent_month
              AND NOT """
        + WRITTEN_OFF_ADJUSTMENT.format(adjustment="a.id"),
    ),
    # The other side of a written-off adjustment is 6160.
    (
        """            jsonb_build_object('account',
                CASE WHEN a.category = 'RENT'
                    THEN app.gl_rent_account(a.period_start, timezone(zone.tz, side.at)::date)
                    ELSE a.other_code END,""",
        """            jsonb_build_object('account',
                CASE WHEN a.written_off THEN '6160'
                    WHEN a.category = 'RENT'
                    THEN app.gl_rent_account(a.period_start, timezone(zone.tz, side.at)::date)
                    ELSE a.other_code END,""",
    ),
    (
        """        SELECT '' AS suffix, a.occurred_at AS at, ' adjusted' AS what,""",
        """        SELECT '' AS suffix, a.occurred_at AS at,
            CASE WHEN a.written_off THEN ' written off' ELSE ' adjusted' END AS what,""",
    ),
    # A Refund correction posts by itself (owner 03/11/2026 13:05 and 13:10): money given back
    # comes into the Refund method's account and the value goes back to the Refund's source; its
    # reversal does the opposite; a Refund recovered by a charge gives the value back to the
    # source against 4080, as the recovery Invoice itself posts 1100 against 4080.
    (
        """    -- A Refund correction changes what a Refund took out; it needs an adjusting entry.
    SELECT 'REFUND_CORRECTION', k.id, 'refund_correction:' || k.id,
        timezone(zone.tz, k.occurred_at)::date, k.occurred_at, 'AUTO',
        'Refund ' || r.refund_number || ' corrected',
        'A Refund correction needs an adjusting entry from the Owner', '[]'::jsonb
    FROM app.refund_corrections AS k
    JOIN refund AS r ON r.id = k.refund_id
    CROSS JOIN zone""",
        """    -- A Refund correction: the money given back, its reversal, or a Refund recovered by a charge.
    SELECT 'REFUND_CORRECTION', k.id, 'refund_correction:' || k.id,
        timezone(zone.tz, k.occurred_at)::date, k.occurred_at, 'AUTO',
        'Refund ' || r.refund_number || CASE k.correction_kind
            WHEN 'VALUE_CORRECTION' THEN ' money given back'
            WHEN 'CORRECTION_REVERSAL' THEN ' money given back undone'
            ELSE ' recovered by a charge' END,
        CASE WHEN k.correction_kind <> 'RECOVERED_BY_CHARGE' AND r.method_code IS NULL
            THEN 'No ledger account is set for the Refund method' END,
        jsonb_build_array(
            jsonb_build_object('account', CASE
                    WHEN k.correction_kind = 'RECOVERED_BY_CHARGE' THEN '4080'
                    WHEN k.correction_kind = 'VALUE_CORRECTION' THEN r.method_code
                    WHEN r.source_deposit_id IS NOT NULL THEN r.deposit_code
                    WHEN r.source_customer_credit_id IS NOT NULL THEN '2200' ELSE '2210' END,
                'debit_cents', abs(k.source_balance_effect_usd_cents), 'memo', r.refund_number,
                'customer_id', r.recipient_customer_id, 'lease_id', r.deposit_lease_id,
                'unit_id', r.deposit_unit_id),
            jsonb_build_object('account', CASE
                    WHEN k.correction_kind = 'CORRECTION_REVERSAL' THEN r.method_code
                    WHEN r.source_deposit_id IS NOT NULL THEN r.deposit_code
                    WHEN r.source_customer_credit_id IS NOT NULL THEN '2200' ELSE '2210' END,
                'credit_cents', abs(k.source_balance_effect_usd_cents), 'memo', r.refund_number,
                'customer_id', r.recipient_customer_id, 'lease_id', r.deposit_lease_id,
                'unit_id', r.deposit_unit_id))
    FROM app.refund_corrections AS k
    JOIN refund AS r ON r.id = k.refund_id
    CROSS JOIN zone
    WHERE (r.source_deposit_id IS NOT NULL OR EXISTS (
        SELECT 1 FROM app.payments AS p
        LEFT JOIN app.customer_credits AS c ON c.source_payment_id = p.id
        WHERE p.property_id = p_property
          AND (p.id = r.source_payment_id OR c.id = r.source_customer_credit_id)))""",
    ),
    # A written-off Late-payment charge: 6160 instead of 4050.
    (
        """            jsonb_build_object('account', '4050',
                CASE WHEN k.correction_kind = 'REDUCTION_REVERSAL' THEN 'credit_cents' ELSE 'debit_cents' END,""",
        """            jsonb_build_object('account', CASE WHEN """
        + WRITTEN_OFF_LATE
        + """ THEN '6160' ELSE '4050' END,
                CASE WHEN k.correction_kind = 'REDUCTION_REVERSAL' THEN 'credit_cents' ELSE 'debit_cents' END,""",
    ),
)


def _module(file_name: str) -> ModuleType:
    path = Path(__file__).with_name(file_name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _literal_colons(sql: str) -> str:
    """Keep ``'invoice:...:issue'`` text from reading as a SQLAlchemy bind parameter."""
    return re.sub(r"(?<![:\w\\]):(?=\w)", r"\\:", sql)


def _events(changed: bool) -> str:
    """The automatic posting's record list, as migration 265 made it or with write-offs."""
    events = str(_module("20270415_265_gl_auto_posting.py").EVENTS)
    if changed:
        for old, new in EVENT_CHANGES:
            if events.count(old) != 1:
                raise RuntimeError(f"Automatic posting text not found once: {old[:60]}")
            events = events.replace(old, new)
    return events.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def upgrade() -> None:
    op.execute(_literal_colons(_events(True)))
    op.execute(_literal_colons(WRITE_OFF))
    op.execute(f"REVOKE ALL ON FUNCTION {WRITE_OFF_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {WRITE_OFF_SIGNATURE} TO prm_runtime")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM app.gl_write_offs) THEN
                RAISE EXCEPTION 'Write-offs exist; they cannot be rolled back'
                    USING ERRCODE = '55000';
            END IF;
        END $$;
        """
    )
    op.execute(f"DROP FUNCTION {WRITE_OFF_SIGNATURE}")
    op.execute(_literal_colons(_events(False)))
