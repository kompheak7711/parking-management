# ruff: noqa: E501
"""Customer Ledger events for Deposit applications; confirmations wait for a receipt reversal draft.

V1-056 sub-slice 8a-2 (BR-SETTLE-009, BR-SETTLE-016, BR-LEDGER-003, BR-AUTH-010).

- A new Customer Ledger projection version adds the event DEPOSIT_APPLIED for each Final
  Settlement Deposit application (migration 86). The Deposit owner's ledger shows the Deposit
  applied, naming the obligation and its Customer; the ledger of the Customer named on the
  Invoice or Late-payment Charge shows the obligation paid by the Deposit application (owner
  answers to Q-2026-10-05-20 and Q-2026-10-05-21). When both are the same Customer, the event
  has one header with both components. Every other component is unchanged, so every earlier
  projection result stays the same; until this migration no application could exist outside
  tests, because no role can write one.
- The ledger page accepts DEPOSIT_APPLIED as a history filter.
- The Deposit's own history (the Deposit ledger read) shows each application through the bounded
  read app.deposit_application_history; the runtime role gets no table privilege.
- Owner answer 2 to Q-2026-10-05-23 (2026-10-05), an approved tightening: while a Deposit receipt
  reversal draft is pending, the confirmation of a Refund draft or a forfeiture draft for the
  same Deposit is refused; recording those drafts stays allowed. A forfeiture reversal draft and
  the receipt reversal draft itself are not Refund or forfeiture drafts and are not affected.
  The receipt reversal draft recorder now also locks the Deposit row, so no Refund or forfeiture
  confirmation commits while a receipt reversal draft for the same Deposit is pending or still
  being recorded. This relies on READ COMMITTED, the isolation every confirm uses: the trigger's
  query takes a fresh snapshot after the wait for the Deposit row.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from sqlalchemy import text

revision = "20261023_88"
down_revision = "20261022_87"
branch_labels = None
depends_on = None

LEDGER_PAGE = (
    "app.customer_ledger_page(uuid,uuid,uuid,text,integer,timestamptz,timestamptz,text,text,"
    "uuid,timestamptz,text,uuid,text)"
)
WAIT_GUARD = "app.refuse_confirmation_during_receipt_reversal_draft()"
HISTORY = "app.deposit_application_history(uuid,uuid)"
RECORD_REVERSAL = "app.record_deposit_receipt_reversal_draft(uuid,uuid,uuid,uuid,uuid,text,text)"


def _module(file_name: str, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file_name))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Customer ledger projection source is missing: {file_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deposit_application_components(ledger: ModuleType) -> list[str]:
    """The Deposit owner's component and the obligation owner's component of one application."""
    source = (
        "app.deposit_applications a JOIN app.deposits d ON d.id=a.deposit_id "
        "LEFT JOIN app.invoices i ON i.id=a.invoice_id "
        "LEFT JOIN app.late_payment_charges c ON c.id=a.late_payment_charge_id "
    )
    obligation_customer = "COALESCE(i.customer_id,c.customer_id)"
    common = dict(
        kind="DEPOSIT_APPLIED",
        order=75,
        table="deposit_applications",
        identity="a.id",
        instant="a.occurred_at",
        prop="app.deposit_property_id(d.id)",
        invoice="a.invoice_id",
        charge="a.late_payment_charge_id",
        deposit="d.id",
        amount="a.amount_usd_cents",
        effect="-a.amount_usd_cents::numeric",
        # The same evidence on both components, so one Customer gets exactly one header.
        audit=(
            "jsonb_build_object('application_id',a.id,'final_settlement_id',a.final_settlement_id,"
            "'application_stage',a.application_stage,'application_order',a.application_order,"
            "'deposit_type',d.deposit_type,'deposit_customer_id',d.customer_id,"
            "'target_kind',a.target_kind,'target_customer_id'," + obligation_customer + ","
            "'reason',a.reason)"
        ),
    )
    return [
        ledger.component(
            customer="d.customer_id",
            source=source,
            bucket=(
                "CASE d.deposit_type WHEN 'SECURITY' THEN 'SECURITY_DEPOSIT' ELSE 'PET_DEPOSIT' END"
            ),
            balance_source="d.id",
            **common,
        ),
        ledger.component(
            customer=obligation_customer,
            source=source + "LEFT JOIN app.invoice_lines l ON l.id=a.invoice_line_id",
            bucket=(
                "CASE WHEN a.invoice_line_id IS NOT NULL THEN 'INVOICE' "
                "ELSE 'LATE_PAYMENT_CHARGE' END"
            ),
            balance_source="COALESCE(a.invoice_line_id,a.late_payment_charge_id)",
            line="a.invoice_line_id",
            category="l.category",
            description="l.description",
            **common,
        ),
    ]


def _ledger_projection() -> str:
    """The revision 79 projection (Deposit Refunds on the Deposit owner) plus the applications."""
    previous = _module("20261014_79_refund_signer_recipient.py", "refund_signer_recipient_79")
    ledger = _module("20260909_48_customer_ledger_projection.py", "customer_ledger_projection_48")
    view = str(previous._ledger_projection())
    prefix = "CREATE OR REPLACE VIEW app.customer_ledger_effects WITH(security_invoker=true) AS "
    if not view.startswith(prefix) or "deposit_applications" in view:
        raise RuntimeError("Customer ledger projection contract changed")
    return view + " UNION ALL " + " UNION ALL ".join(_deposit_application_components(ledger))


def _patch(signature: str, before: str, after: str) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    if definition.count(before) != 1:
        raise RuntimeError(f"Deposit application ledger source contract changed: {signature}")
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition.replace(before, after))


def upgrade() -> None:
    op.execute(_ledger_projection())
    # The receipt reversal draft recorder also locks the Deposit row, in the same order as the
    # receipt reversal confirm (advisory lock, then row). The Pet Refund and Reservation Deposit
    # confirms lock that row, so a confirm waits for a receipt reversal draft being recorded
    # and then sees it, and the recorder waits for a confirm in progress and then sees it
    # decided. Without the row lock a Refund draft recorded after the recorder's pending-draft
    # check could be confirmed before the receipt reversal draft commits. Both sides rely on
    # READ COMMITTED: each statement after a lock wait takes a fresh snapshot.
    _patch(
        RECORD_REVERSAL,
        "            PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || (v_source->>'deposit_id'),0));\n"
        "            v_source:=app.deposit_receipt_reversal_source(p_property,p_receipt);\n",
        "            PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || (v_source->>'deposit_id'),0));\n"
        "            PERFORM 1 FROM app.deposits WHERE id=(v_source->>'deposit_id')::uuid FOR UPDATE;\n"
        "            v_source:=app.deposit_receipt_reversal_source(p_property,p_receipt);\n",
    )
    _patch(
        LEDGER_PAGE,
        "'DEPOSIT_DISPOSITION_REVERSED',\n                    'REFUND_PAID',",
        "'DEPOSIT_DISPOSITION_REVERSED',\n                    'DEPOSIT_APPLIED','REFUND_PAID',",
    )
    op.execute("""
        -- Owner answer 2 to Q-2026-10-05-23 (approved tightening): no Refund or forfeiture of a
        -- Deposit is confirmed while a receipt reversal draft for that Deposit waits, because
        -- the money may never have been received. Every confirm writes its decision here, so
        -- every present and future confirmation of these kinds is covered.
        CREATE FUNCTION app.refuse_confirmation_during_receipt_reversal_draft()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE;
        BEGIN
            IF NEW.decision IS DISTINCT FROM 'CONFIRMED' THEN RETURN NEW; END IF;
            SELECT * INTO v_draft FROM app.financial_drafts WHERE id=NEW.draft_id;
            IF NOT FOUND OR v_draft.kind NOT IN ('REFUND','DEPOSIT_FORFEITURE')
                OR v_draft.payload->>'variant' IN ('DEPOSIT_RECEIPT_REVERSAL','LEASE_FORFEITURE_REVERSAL')
                OR (v_draft.payload->>'deposit_id' IS NULL AND v_draft.payload->>'reservation_id' IS NULL)
            THEN RETURN NEW; END IF;
            IF EXISTS (SELECT 1 FROM app.financial_drafts reversal
                WHERE reversal.kind='DEPOSIT_FORFEITURE'
                  AND reversal.payload->>'variant'='DEPOSIT_RECEIPT_REVERSAL'
                  AND reversal.id<>v_draft.id
                  AND reversal.payload->>'deposit_id' IN (
                      SELECT deposit.id::text FROM app.deposits deposit
                      WHERE deposit.id=(v_draft.payload->>'deposit_id')::uuid
                      UNION ALL
                      SELECT deposit.id::text FROM app.deposits deposit
                      WHERE deposit.reservation_id=(v_draft.payload->>'reservation_id')::uuid)
                  AND NOT EXISTS (SELECT 1 FROM app.financial_draft_decisions decision
                      WHERE decision.draft_id=reversal.id))
            THEN RAISE EXCEPTION 'A Deposit receipt reversal draft for this Deposit is waiting'
                USING ERRCODE='55000'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER financial_draft_decisions_wait_for_receipt_reversal
            BEFORE INSERT ON app.financial_draft_decisions
            FOR EACH ROW EXECUTE FUNCTION app.refuse_confirmation_during_receipt_reversal_draft();

        -- The Deposit's own history (BR-SETTLE-009): the applications of one Deposit of one
        -- Property. The runtime role gets EXECUTE on this function only and no table privilege;
        -- the application checks the Deposit read capability for that Property first.
        CREATE FUNCTION app.deposit_application_history(p_property uuid,p_deposit uuid)
        RETURNS TABLE(application_id uuid,final_settlement_id uuid,target_kind text,target_id uuid,
            amount_usd_cents bigint,reason text,actor_id uuid,authorization_reference text,
            occurred_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT application.id,application.final_settlement_id,application.target_kind,
                COALESCE(application.invoice_line_id,application.late_payment_charge_id),
                application.amount_usd_cents,application.reason,application.actor_id,
                application.authorization_reference,application.occurred_at
            FROM app.deposit_applications application
            WHERE application.deposit_id=p_deposit
              AND app.deposit_property_id(application.deposit_id)=p_property
        $$;
    """)
    for function in (WAIT_GUARD, HISTORY):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {HISTORY} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("Deposit application ledger events are forward-only")
