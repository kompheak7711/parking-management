# ruff: noqa: E501
"""Post-settlement correction: REFUND of a Deposit-paid Late-payment Charge (V1-056 sub-slice 10c-3b-2).

BR-SETTLE-013, BR-SETTLE-008, BR-LATE-005, BR-CREDIT-014, BR-REFUND-014, DL-032, BR-AUTH-010;
owner answer 1 to Q-2026-10-09-66 and the owner answer to Q-2026-10-07-46, Q-2026-10-07-41
answers 1 and 2, Q-2026-10-07-42 answers 1 and 2:

- The Late-payment Charge REFUND correction of sub-slice 10c-3b-1 also releases Deposit
  applications on the Charge, newest first with the Payment allocations and Credit applications
  (Q-41 answer 2). A released Deposit application is reversed whole, as a Deposit application
  reversal linked to the correction (sub-slice 10c-2a-1); its value goes back to its Deposit and
  never becomes Customer Credit, and the shared DL-032 step applies or refunds it.
- The 8a-1 refusal of a Late-payment Charge correction while a Deposit application on the Charge
  stands lets through only a Charge correction linked to a correction of that Charge's own
  Settlement, confirmed in this transaction by that correction's approver (the Q-46 answer, as for
  an Invoice Adjustment); every unlinked Charge correction stays refused.

Relaxing exact-text patches of three functions (owner, SECURITY DEFINER, settings and grants kept)
and one new internal function; no table changes.
"""

from alembic import op
from sqlalchemy import text

revision = "20261118_114"
down_revision = "20261117_113"
branch_labels = None
depends_on = None

DEPOSIT_APPLIED = "app.refuse_deposit_applied_obligation_change()"
DEPOSIT_APPLIED_REPLACEMENTS = (
    (
        "            IF TG_TABLE_NAME='late_payment_charge_corrections' THEN\n",
        "            IF TG_TABLE_NAME='late_payment_charge_corrections' THEN\n"
        "                -- Sub-slice 10c-3b-2 (owner answer 1 to Q-2026-10-09-66, the Q-46 answer): a\n"
        "                -- Charge correction linked to a post-settlement correction of its Charge's own\n"
        "                -- Settlement, confirmed in this transaction by that correction's approver,\n"
        "                -- passes; every other one stays refused.\n"
        "                IF app.settlement_correction_charge_correction_allowed(NEW.late_payment_charge_id,NEW.id,NEW.actor_id) THEN\n"
        "                    RETURN NEW; END IF;\n",
    ),
)

PLAN = "app.settlement_late_charge_refund_plan(uuid,uuid,jsonb)"
PLAN_REPLACEMENTS = (
    (
        "        -- 8a-1: a Charge that a Deposit application paid takes no correction until sub-slice 10c-3b-2.\n"
        "        IF (v_summary->>'deposit_total_usd_cents')::bigint>0 THEN\n"
        "            RAISE EXCEPTION 'A Deposit application paid this obligation at Final Settlement'\n"
        "                USING ERRCODE='55000'; END IF;\n",
        "        -- Sub-slice 10c-3b-2: a Deposit application on the Charge is released like the other\n"
        "        -- sources; the 8a-1 refusal lets only the correction's own linked Charge correction through.\n",
    ),
    (
        "            v_released:=v_released||jsonb_build_array((v_source-'on_charge_usd_cents'-'at')\n"
        "                ||jsonb_build_object('released_usd_cents',v_release));\n",
        "            v_released:=v_released||jsonb_build_array((v_source-'on_charge_usd_cents'-'at')\n"
        "                -- Sub-slice 10c-3b-2: a Deposit application keeps its whole amount beside the\n"
        "                -- released part (as the Invoice-line plan), so the overlay gives its Deposit\n"
        "                -- all of it and leaves the unreleased rest as the Charge's obligation.\n"
        "                ||CASE WHEN v_source->>'kind'='DEPOSIT_APPLICATION'\n"
        "                    THEN jsonb_build_object('application_usd_cents',v_source->'on_charge_usd_cents')\n"
        "                    ELSE '{}'::jsonb END\n"
        "                ||jsonb_build_object('released_usd_cents',v_release));\n",
    ),
)

CONFIRM = "app.confirm_settlement_late_charge_refund(uuid,uuid,uuid,text)"
CONFIRM_REPLACEMENTS = (
    (
        "        -- first. (A Deposit application is never a source until sub-slice 10c-3b-2: the plan refuses\n"
        "        -- a Deposit-paid Charge.)\n",
        "        -- first. A Deposit application is reversed whole and its value goes back to its Deposit\n"
        "        -- (sub-slice 10c-3b-2).\n",
    ),
    (
        "            ELSE\n"
        "                PERFORM app.link_settlement_correction_effect(v_correction,\n"
        "                    'credit_application_reversal_id',v_new);\n",
        "            ELSIF v_source->>'kind'='CREDIT_APPLICATION' THEN\n"
        "                PERFORM app.link_settlement_correction_effect(v_correction,\n"
        "                    'credit_application_reversal_id',v_new);\n",
    ),
    (
        "                    'credits.applications.reverse');\n"
        "            END IF;\n"
        "        END LOOP;\n",
        "                    'credits.applications.reverse');\n"
        "            ELSE\n"
        "                -- Sub-slice 10c-3b-2 (sub-slice 10c-2a-1 record): only the plan's step pays the\n"
        "                -- Deposit application's unreleased rest again; it never becomes Credit.\n"
        "                PERFORM app.link_settlement_correction_effect(v_correction,\n"
        "                    'deposit_application_reversal_id',v_new);\n"
        "                INSERT INTO app.deposit_application_reversals(id,deposit_application_id,reason,\n"
        "                    occurred_at,actor_id,authorization_reference)\n"
        "                VALUES(v_new,(v_source->>'id')::uuid,v_draft.reason,\n"
        "                    GREATEST(app.settlement_late_charge_instant(v_charge.id,NULL),\n"
        "                        COALESCE(app.deposit_balance_latest_at((v_source->>'deposit_id')::uuid),'-infinity')\n"
        "                            +interval '1 microsecond'),\n"
        "                    p_actor,'financial.approve');\n"
        "            END IF;\n"
        "        END LOOP;\n",
    ),
    (
        "        -- 3). It passes the 8e-1 refusal only because it is linked to this correction first. Its\n",
        "        -- 3). It passes the 8e-1 refusal, and the 8a-1 refusal while an older Deposit application\n"
        "        -- stays on the Charge (sub-slice 10c-3b-2), only because it is linked to this correction\n"
        "        -- first. Its\n",
    ),
    (
        "                'released_sources',v_result->'released_sources',\n",
        "                'released_sources',v_result->'released_sources',\n"
        "                -- Sub-slice 10c-3b-2: the Deposit application reversals.\n"
        "                'deposit_application_reversals',v_result->'deposit_application_reversals',\n",
    ),
)

PATCHES = (
    (DEPOSIT_APPLIED, DEPOSIT_APPLIED_REPLACEMENTS),
    (PLAN, PLAN_REPLACEMENTS),
    (CONFIRM, CONFIRM_REPLACEMENTS),
)

SQL = r"""
    -- The Q-46 answer for a Late-payment Charge (owner answer 1 to Q-2026-10-09-66): a Charge
    -- correction linked to a post-settlement correction of its Charge's own (closed) Settlement, the
    -- Settlement of the Lease of the Charge's source Invoice, confirmed in this transaction by that
    -- correction's approver (the twin of app.settlement_correction_adjustment_allowed).
    CREATE FUNCTION app.settlement_correction_charge_correction_allowed(p_charge uuid,
        p_charge_correction uuid,p_actor uuid)
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
            WHERE charge.id=p_charge AND correction.actor_id=p_actor AND decision.decided_by=p_actor
              AND decision.authorization_reference='financial.approve'
              AND decision.result->>'transaction_id'=pg_current_xact_id()::text
              AND decision.decided_at>=transaction_timestamp())
    $$;
"""

INTERNAL = "app.settlement_correction_charge_correction_allowed(uuid,uuid,uuid)"


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
            raise RuntimeError(f"Deposit-paid Charge Refund source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(SQL)
    op.execute(
        f"REVOKE ALL ON FUNCTION {INTERNAL} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Deposit-paid Charge Refund migration is forward-only")
