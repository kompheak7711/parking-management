# ruff: noqa: E501
"""Deposit receipt reversal drafts (BR-AUTH-010; V1-056 sub-slice 8r).

Owner answer to Q-2026-10-05-22 (2026-10-05), Option (a), an approved tightening that replaces
the answer to Q-2026-10-04-13 ("Deposit receipt reversal stays as it is"):
- A one-call receipt reversal returned the receipt's value to its Payment, which stays RECEIVED,
  so a one-call allocation or Credit recognition could then let Deposit money pay debt without a
  draft or an approver. A Deposit receipt reversal is now a draft: Staff holding deposits.correct
  record it, and only a financial.approve holder confirms it, like the Lease forfeiture reversal
  (sub-slice 6b). The confirmation runs the existing reversal function (migration 28) as its owner
  with the approver as actor, so every earlier receipt reversal rule applies.
- This covers Lease and Reservation Deposit receipts (owner answer (c)): both are funded by a
  Payment of the Customer, whose freed value a one-call allocation could use.
- The financial role loses EXECUTE on app.reverse_deposit_receipt_v2 (the tightening).
- A receipt reversal is refused while a REFUND or DEPOSIT_FORFEITURE draft for that Deposit is
  pending: the receipt reversal guard also matches the drafts' deposit_id, not only a
  Reservation id. The Final Settlement drafts (8c, 8e) must extend this check.

A returned transfer still works: the approver confirms the receipt reversal draft, then the
Payment is reversed as before.
"""

from alembic import op
from sqlalchemy import text

revision = "20261022_87"
down_revision = "20261021_86"
branch_labels = None
depends_on = None

ONE_CALL = "app.reverse_deposit_receipt_v2(uuid,uuid,uuid,text,uuid,uuid,text,text)"
SOURCE = "app.deposit_receipt_reversal_source(uuid,uuid)"
RECORD_DRAFT = "app.record_deposit_receipt_reversal_draft(uuid,uuid,uuid,uuid,uuid,text,text)"
CONFIRM_DRAFT = "app.confirm_deposit_receipt_reversal_draft(uuid,uuid,uuid,uuid,text)"


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
            raise RuntimeError(f"Deposit receipt reversal source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    # A pending REFUND or DEPOSIT_FORFEITURE draft naming the Deposit, not only its Reservation,
    # refuses a receipt reversal.
    _patch(
        "app.validate_deposit_receipt_reversal()",
        (
            (
                "                  ON draft.payload->>'reservation_id' = deposit.reservation_id::text\n",
                "                  ON (draft.payload->>'reservation_id' = deposit.reservation_id::text\n"
                "                      OR draft.payload->>'deposit_id' = deposit.id::text)\n",
            ),
        ),
    )
    op.execute("""
        -- Finds the pending drafts of one Deposit without scanning every draft.
        CREATE INDEX financial_drafts_deposit_idx
            ON app.financial_drafts ((payload->>'deposit_id'))
            WHERE kind IN ('REFUND','DEPOSIT_FORFEITURE');

        -- Internal: the current reversal source of one Deposit receipt, or a refusal.
        CREATE FUNCTION app.deposit_receipt_reversal_source(p_property uuid,p_receipt uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_receipt app.deposit_receipts%ROWTYPE;
        BEGIN
            SELECT * INTO v_receipt FROM app.deposit_receipts WHERE id=p_receipt;
            IF NOT FOUND OR app.deposit_property_id(v_receipt.deposit_id) IS DISTINCT FROM p_property
            THEN RAISE EXCEPTION 'Deposit receipt was not found' USING ERRCODE='P0002'; END IF;
            IF EXISTS (SELECT 1 FROM app.deposit_receipt_reversals reversal
                WHERE reversal.deposit_receipt_id=p_receipt)
            THEN RAISE EXCEPTION 'The Deposit receipt is already reversed' USING ERRCODE='22023'; END IF;
            RETURN jsonb_build_object('deposit_id',v_receipt.deposit_id,'receipt_id',v_receipt.id,
                'amount_usd_cents',v_receipt.amount_usd_cents,
                'state_version',app.deposit_disposition_state_version(v_receipt.deposit_id));
        END $$;

        -- Staff record the reversal of one receipt as a draft (deposits.correct); it has no
        -- financial effect until a financial.approve holder confirms.
        CREATE FUNCTION app.record_deposit_receipt_reversal_draft(p_property uuid,p_actor uuid,p_draft uuid,
            p_receipt uuid,p_reversal uuid,p_reason text,p_authorization text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_input jsonb; v_source jsonb; v_existing app.financial_drafts%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property,p_actor);
            PERFORM app.assert_active_financial_actor(p_actor,p_property);
            IF p_authorization IS DISTINCT FROM 'deposits.correct'
            THEN RAISE EXCEPTION 'Deposit receipt reversal draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
            IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_receipt IS NULL
                OR p_reversal IS NULL OR p_reversal='00000000-0000-0000-0000-000000000000'
                OR p_reversal IN (p_draft,p_receipt)
                OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
            THEN RAISE EXCEPTION 'Deposit receipt reversal draft input is invalid'
                USING ERRCODE='22023'; END IF;
            v_input:=jsonb_build_object('variant','DEPOSIT_RECEIPT_REVERSAL','receipt_id',p_receipt,
                'reversal_id',p_reversal,'reason',p_reason);
            -- An exact repeat replays before any current-state check.
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
            SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
            IF FOUND THEN
                IF v_existing.property_id=p_property AND v_existing.kind='DEPOSIT_FORFEITURE'
                    AND v_existing.prepared_by=p_actor
                    AND jsonb_build_object('variant',v_existing.payload->'variant',
                        'receipt_id',v_existing.payload->'receipt_id',
                        'reversal_id',v_existing.payload->'reversal_id',
                        'reason',v_existing.payload->'reason')=v_input
                THEN RETURN app.financial_draft_json(v_existing); END IF;
                RAISE EXCEPTION 'Deposit receipt reversal draft identity was reused' USING ERRCODE='P5205';
            END IF;
            v_source:=app.deposit_receipt_reversal_source(p_property,p_receipt);
            -- The same per-Deposit lock as the Lease forfeiture drafts.
            PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || (v_source->>'deposit_id'),0));
            v_source:=app.deposit_receipt_reversal_source(p_property,p_receipt);
            -- A pending REFUND or DEPOSIT_FORFEITURE draft for this Deposit (or its Reservation) waits first.
            IF EXISTS (SELECT 1 FROM app.deposits deposit
                JOIN app.financial_drafts draft
                  ON (draft.payload->>'deposit_id'=deposit.id::text
                      OR draft.payload->>'reservation_id'=deposit.reservation_id::text)
                 AND draft.kind IN ('REFUND','DEPOSIT_FORFEITURE')
                WHERE deposit.id=(v_source->>'deposit_id')::uuid
                  AND NOT EXISTS (SELECT 1 FROM app.financial_draft_decisions decision
                      WHERE decision.draft_id=draft.id))
            THEN RAISE EXCEPTION 'A draft for this Deposit is already waiting' USING ERRCODE='55000'; END IF;
            -- A reversal id is used once: not by a recorded receipt reversal, an audit event (the
            -- reversal audit takes its id) or any draft's reversal, correction, disposition or outcome id.
            IF EXISTS (SELECT 1 FROM app.deposit_receipt_reversals WHERE id=p_reversal)
                OR EXISTS (SELECT 1 FROM app.audit_events WHERE id=p_reversal)
                OR EXISTS (SELECT 1 FROM app.financial_drafts draft
                    WHERE p_reversal::text IN (draft.payload->>'reversal_id',draft.payload->>'correction_id',
                        draft.payload->>'disposition_id',draft.payload->>'outcome_id'))
            THEN RAISE EXCEPTION 'Deposit receipt reversal identity was reused' USING ERRCODE='P5205'; END IF;
            RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'DEPOSIT_FORFEITURE','deposits.correct',
                v_input || v_source,'deposit-state:' || (v_source->>'state_version'),p_reason);
        END $$;

        -- A financial.approve holder confirms: the existing reversal function runs with the
        -- approver as actor, so every earlier receipt reversal rule applies.
        CREATE FUNCTION app.confirm_deposit_receipt_reversal_draft(p_property uuid,p_actor uuid,p_receipt uuid,
            p_draft uuid,p_authorization text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE; v_source jsonb; v_snapshot jsonb; v_digest text;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property,p_actor);
            PERFORM app.assert_active_financial_actor(p_actor,p_property);
            IF p_authorization IS DISTINCT FROM 'financial.approve' THEN
                RAISE EXCEPTION 'Only financial.approve may confirm a receipt reversal draft' USING ERRCODE='42501'; END IF;
            IF p_draft IS NULL OR p_receipt IS NULL THEN
                RAISE EXCEPTION 'Deposit receipt reversal confirmation is invalid' USING ERRCODE='22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
            SELECT draft.* INTO v_draft FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
            WHERE draft.id=p_draft AND draft.property_id=p_property AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor AND draft.payload->>'variant'='DEPOSIT_RECEIPT_REVERSAL'
              AND draft.payload->>'receipt_id'=p_receipt::text;
            IF FOUND THEN
                -- An exact replay returns the stored result of the first confirmation.
                SELECT command.result_snapshot INTO STRICT v_snapshot FROM app.deposit_commands command
                WHERE command.actor_id=p_actor AND command.property_id=p_property
                  AND command.action='deposit.receipt.reverse' AND command.idempotency_key=p_draft;
                RETURN jsonb_build_object('draft',app.financial_draft_json(v_draft),'deposit',v_snapshot);
            END IF;
            v_draft:=app.lock_pending_financial_draft(p_property,p_draft);
            IF v_draft.kind<>'DEPOSIT_FORFEITURE' OR v_draft.prepare_capability<>'deposits.correct'
                OR v_draft.payload->>'variant' IS DISTINCT FROM 'DEPOSIT_RECEIPT_REVERSAL'
                OR v_draft.payload->>'receipt_id' IS DISTINCT FROM p_receipt::text
            THEN RAISE EXCEPTION 'Financial draft was not found' USING ERRCODE='P0002'; END IF;
            IF EXISTS (SELECT 1 FROM app.deposit_commands command
                WHERE command.actor_id=p_actor AND command.property_id=p_property
                  AND command.action='deposit.receipt.reverse' AND command.idempotency_key=p_draft)
            THEN RAISE EXCEPTION 'Deposit receipt reversal draft identity was reused' USING ERRCODE='P5205'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || (v_draft.payload->>'deposit_id'),0));
            -- Lock the Deposit row before the stale check, so no other Deposit change can commit
            -- between the check and the reversal (the reversal locks the same row later).
            PERFORM 1 FROM app.deposits WHERE id=(v_draft.payload->>'deposit_id')::uuid FOR UPDATE;
            v_source:=app.deposit_receipt_reversal_source(p_property,p_receipt);
            -- A draft is stale when the Deposit changed since it was recorded.
            IF (v_source->>'state_version') IS DISTINCT FROM (v_draft.payload->>'state_version')
                OR (v_source->>'deposit_id') IS DISTINCT FROM (v_draft.payload->>'deposit_id')
            THEN RAISE EXCEPTION 'Deposit receipt reversal draft is stale' USING ERRCODE='23514'; END IF;
            -- Decide first, so the receipt reversal guard no longer sees this draft as pending.
            PERFORM app.confirm_financial_draft_record(p_property,p_actor,p_draft,'DEPOSIT_FORFEITURE',
                jsonb_build_object('deposit_id',v_draft.payload->>'deposit_id','receipt_id',p_receipt,
                    'reversal_id',v_draft.payload->>'reversal_id'),'financial.approve');
            v_digest:=encode(sha256(convert_to('deposit-receipt-reversal-draft:' || p_draft::text,'UTF8')),'hex');
            PERFORM app.reverse_deposit_receipt_v2(p_property,p_actor,p_draft,v_digest,
                (v_draft.payload->>'reversal_id')::uuid,p_receipt,v_draft.payload->>'reason','deposits.correct');
            SELECT command.result_snapshot INTO STRICT v_snapshot FROM app.deposit_commands command
            WHERE command.actor_id=p_actor AND command.property_id=p_property
              AND command.action='deposit.receipt.reverse' AND command.idempotency_key=p_draft;
            RETURN jsonb_build_object('draft',app.financial_draft_json(v_draft),'deposit',v_snapshot);
        END $$;
    """)
    for function in (SOURCE, RECORD_DRAFT, CONFIRM_DRAFT):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD_DRAFT}, {CONFIRM_DRAFT} TO prm_financial")
    # Approved tightening (owner answer to Q-2026-10-05-22): no one-call receipt reversal.
    op.execute(f"REVOKE EXECUTE ON FUNCTION {ONE_CALL} FROM prm_financial")


def downgrade() -> None:
    raise RuntimeError("Deposit receipt reversal drafts are forward-only")
