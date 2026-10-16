# ruff: noqa: E501
"""The 8a-1 allow functions need the row's own correlation and a draft that names the obligation
(V1-056 sub-slice 10c-3c-1).

BR-SETTLE-012, BR-SETTLE-013, BR-AUTH-010, DL-032; DB-SETTLE-005; owner answer 3 to
Q-2026-10-10-69 and answer (a) to Q-2026-10-10-70 (an approved tightening, built before any new
writer links an Adjustment or a Charge correction):

- Two new internal overloads, each the old body plus two conditions. An Invoice Adjustment passes
  the 8a-1 refusal only when its `source_reference` is `settlement-correction:<the correction>`
  and the correction's draft is a `CHARGE_REDUCTION` or `REFUND` with no `target_kind` naming
  exactly the Adjustment's Invoice and line. A Late-payment Charge correction passes only when its
  `correlation_id` is the correction and the correction's draft is a `CHARGE_REDUCTION` or
  `REFUND` with `target_kind` `LATE_PAYMENT_CHARGE` naming exactly its Charge. The row is not yet
  readable in the BEFORE INSERT refusal, so the refusal passes the row's own values.
- `app.refuse_deposit_applied_obligation_change()` (exact-text patch): its two calls use the new
  overloads. The old three-argument functions stay and have no caller.

Every committed writer that links such a row already meets both conditions (the `CHARGE_REDUCTION`
and `REFUND` confirms of migrations 99, 103, 111, 113 and 114). No table, column, constraint,
trigger, lock or grant change.
"""

from alembic import op
from sqlalchemy import text

revision = "20261217_143"
down_revision = "20261216_142"
branch_labels = None
depends_on = None

ADJUSTMENT_ALLOWED = "app.settlement_correction_adjustment_allowed(uuid,uuid,uuid,uuid,text)"
CHARGE_CORRECTION_ALLOWED = "app.settlement_correction_charge_correction_allowed(uuid,uuid,uuid,uuid)"
NEW_FUNCTIONS = (ADJUSTMENT_ALLOWED, CHARGE_CORRECTION_ALLOWED)

FUNCTION_SQL = """
    -- Q-46 (migration 103) hardened by owner answer 3 to Q-2026-10-10-69: an Invoice Adjustment
    -- linked to a post-settlement correction of its Invoice's own (closed) Settlement, confirmed in
    -- this transaction by that correction's approver, whose reference names that correction and
    -- whose draft names this Invoice line (a CHARGE_REDUCTION or REFUND of an Invoice line).
    CREATE FUNCTION app.settlement_correction_adjustment_allowed(p_invoice uuid,p_line uuid,
        p_adjustment uuid,p_actor uuid,p_source_reference text)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT p_actor IS NOT NULL AND EXISTS(SELECT 1 FROM app.invoices invoice
            JOIN app.final_settlements settlement
                ON settlement.lease_id=invoice.lease_id AND settlement.closed_at IS NOT NULL
            JOIN app.settlement_correction_effects effect ON effect.invoice_adjustment_id=p_adjustment
            JOIN app.settlement_corrections correction
                ON correction.id=effect.settlement_correction_id AND correction.final_settlement_id=settlement.id
            JOIN app.financial_draft_decisions decision
                ON decision.draft_id=correction.correlation_id AND decision.decision='CONFIRMED'
            JOIN app.financial_drafts draft
                ON draft.id=correction.correlation_id AND draft.kind='SETTLEMENT_CORRECTION'
            WHERE invoice.id=p_invoice AND correction.actor_id=p_actor AND decision.decided_by=p_actor
              AND decision.authorization_reference='financial.approve'
              AND decision.result->>'transaction_id'=pg_current_xact_id()::text
              AND decision.decided_at>=transaction_timestamp()
              AND p_source_reference='settlement-correction:' || correction.id::text
              AND draft.payload->'target_kind' IS NULL
              AND ((draft.payload->>'variant'='CHARGE_REDUCTION'
                    AND draft.payload->'reduction'->>'invoice_id'=p_invoice::text
                    AND draft.payload->'reduction'->>'invoice_line_id'=p_line::text)
                OR (draft.payload->>'variant'='REFUND'
                    AND draft.payload->'refund'->>'invoice_id'=p_invoice::text
                    AND draft.payload->'refund'->>'invoice_line_id'=p_line::text)))
    $$;

    -- The twin for a Late-payment Charge correction (migration 114) hardened the same way: its
    -- correlation is the correction, whose draft names this Charge (a CHARGE_REDUCTION or REFUND
    -- of a Late-payment Charge).
    CREATE FUNCTION app.settlement_correction_charge_correction_allowed(p_charge uuid,
        p_charge_correction uuid,p_actor uuid,p_correlation uuid)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT p_actor IS NOT NULL AND EXISTS(SELECT 1 FROM app.late_payment_charges charge
            JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
            JOIN app.final_settlements settlement
                ON settlement.lease_id=invoice.lease_id AND settlement.closed_at IS NOT NULL
            JOIN app.settlement_correction_effects effect
                ON effect.late_payment_charge_correction_id=p_charge_correction
            JOIN app.settlement_corrections correction
                ON correction.id=effect.settlement_correction_id AND correction.final_settlement_id=settlement.id
            JOIN app.financial_draft_decisions decision
                ON decision.draft_id=correction.correlation_id AND decision.decision='CONFIRMED'
            JOIN app.financial_drafts draft
                ON draft.id=correction.correlation_id AND draft.kind='SETTLEMENT_CORRECTION'
            WHERE charge.id=p_charge AND correction.actor_id=p_actor AND decision.decided_by=p_actor
              AND decision.authorization_reference='financial.approve'
              AND decision.result->>'transaction_id'=pg_current_xact_id()::text
              AND decision.decided_at>=transaction_timestamp()
              AND p_correlation=correction.id
              AND draft.payload->>'target_kind'='LATE_PAYMENT_CHARGE'
              AND ((draft.payload->>'variant'='CHARGE_REDUCTION'
                    AND draft.payload->'reduction'->>'late_payment_charge_id'=p_charge::text)
                OR (draft.payload->>'variant'='REFUND'
                    AND draft.payload->'refund'->>'late_payment_charge_id'=p_charge::text)))
    $$;

    REVOKE ALL ON FUNCTION app.settlement_correction_adjustment_allowed(uuid,uuid,uuid,uuid,text)
        FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
    REVOKE ALL ON FUNCTION app.settlement_correction_charge_correction_allowed(uuid,uuid,uuid,uuid)
        FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
"""

REFUSAL = "app.refuse_deposit_applied_obligation_change()"
REFUSAL_REPLACEMENTS = (
    (
        "                IF app.settlement_correction_adjustment_allowed(NEW.invoice_id,NEW.id,NEW.actor_id) THEN\n",
        "                -- Sub-slice 10c-3c-1: the row's own line and reference too.\n"
        "                IF app.settlement_correction_adjustment_allowed(NEW.invoice_id,NEW.invoice_line_id,\n"
        "                    NEW.id,NEW.actor_id,NEW.source_reference) THEN\n",
        1,
    ),
    (
        "                IF app.settlement_correction_charge_correction_allowed(NEW.late_payment_charge_id,NEW.id,NEW.actor_id) THEN\n",
        "                -- Sub-slice 10c-3c-1: the row's own correlation too.\n"
        "                IF app.settlement_correction_charge_correction_allowed(NEW.late_payment_charge_id,\n"
        "                    NEW.id,NEW.actor_id,NEW.correlation_id) THEN\n",
        1,
    ),
)

PATCHES = ((REFUSAL, REFUSAL_REPLACEMENTS),)


def _patch(signature: str, replacements: tuple[tuple[str, str, int], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after, count in replacements:
        if definition.count(before) != count:
            raise RuntimeError(f"Settlement correction allow hardening contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(FUNCTION_SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Settlement correction allow hardening migration is forward-only")
