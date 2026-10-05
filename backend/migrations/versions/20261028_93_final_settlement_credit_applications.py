# ruff: noqa: E501
"""Final Settlement Credit applications (V1-056 sub-slice 8e-2).

BR-CREDIT-006, BR-CREDIT-008, BR-SETTLE-004, BR-SETTLE-009, BR-SETTLE-012, BR-SETTLE-013,
BR-AUTH-010, DL-032; owner answers 1 to 3 to Q-2026-10-06-32 and the owner answers to
Q-2026-10-05-29.

- app.post_final_settlement_credit_application is a new internal writer (no role may call it);
  the Settlement confirm (8e-3) calls it once for each Customer Credit step of the confirmed
  FINAL_SETTLEMENT draft. It writes the same header and detail rows as app.post_credit_application
  (migration 41): the Rent-first proposal with its trace, the Customer's designation recorded as
  text, a direct Late-payment Charge, and on an Invoice without Rent or Service lines the existing
  OTHER_APPLICABLE_OBLIGATION basis with OTHER_CONFIRMED details, which no writer produced before.
  Every existing Credit trigger runs unchanged on these rows: the same Customer (BR-CREDIT-008,
  owner answer to Q-2026-10-05-29), available Credit, target balance, the proposal re-check,
  chronology, reconciliation, history budget and audit.
- The row records the Settlement link (customer_credit_applications.final_settlement_id, docs/004
  DB-CREDIT-002; its NULL-only CHECK becomes a foreign key) and the Settlement's financial.approve
  confirmation as its authorization (the authorization CHECK accepts financial.approve on such
  rows only). Its id is derived from the draft and the step, so each Credit step is written at
  most once; the detail's calculation trace names the draft and the step.
- A source check (before insert) and a deferred check (at commit) tie each such row to a Customer
  Credit step of a FINAL_SETTLEMENT draft of its Settlement: written only while that draft waits
  or is confirmed by the same approver, committed only with the draft CONFIRMED under
  financial.approve by that approver (as the Settlement Refunds of sub-slice 8d), paying exactly
  the obligation and amount of the step, with the basis BR-CREDIT-006 gives. Customer Credit comes
  first (DL-032 step 2): no such row once the Settlement has a Deposit application or a Refund.
- Owner answer 3 to Q-2026-10-06-32: a Credit application the Settlement made is never reversed
  with one call; a correction waits for the post-settlement corrections (slice 10). Ordinary
  Credit applications and their reversals stay open (owner answer 7 to Q-2026-10-05-20).

Additive and relaxing: the relaxed CHECKs accept every earlier row, and the new refusals see
records no writer could create before.
"""

from alembic import op
from sqlalchemy import text

revision = "20261028_93"
down_revision = "20261027_92"
branch_labels = None
depends_on = None

INTERNAL = (
    "app.final_settlement_credit_application_id(uuid,integer)",
    "app.assert_final_settlement_credit_application_source()",
    "app.assert_final_settlement_credit_application_confirmed()",
    "app.refuse_final_settlement_credit_application_reversal()",
    "app.post_final_settlement_credit_application(uuid,uuid,uuid,uuid,integer)",
)
CHECKS = {
    "customer_credit_applications_final_settlement_id_check": "CHECK ((final_settlement_id IS NULL))",
    "customer_credit_applications_authorization_reference_check": "CHECK ((authorization_reference = 'credits.apply'::text))",
}


def _assert_checks() -> None:
    """The two CHECKs this migration relaxes are exactly the ones migration 41 created."""
    found = dict(
        op.get_bind()
        .execute(
            text(
                "SELECT conname,pg_catalog.pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint "
                "WHERE conrelid='app.customer_credit_applications'::regclass AND contype='c' "
                "AND conname = ANY(:names)"
            ),
            {"names": list(CHECKS)},
        )
        .all()
    )
    if found != CHECKS:
        raise RuntimeError("Credit application settlement contract changed")


def upgrade() -> None:
    _assert_checks()
    op.execute("""
        -- Relaxed (owner answers 1 and 2 to Q-2026-10-06-32): a Credit application may name its Final
        -- Settlement (docs/004 DB-CREDIT-002); such a row records the Settlement's financial.approve
        -- confirmation, every other row credits.apply as before.
        ALTER TABLE app.customer_credit_applications
            DROP CONSTRAINT customer_credit_applications_final_settlement_id_check,
            DROP CONSTRAINT customer_credit_applications_authorization_reference_check,
            ADD CONSTRAINT customer_credit_applications_final_settlement_fk
                FOREIGN KEY (final_settlement_id) REFERENCES app.final_settlements(id) ON DELETE RESTRICT,
            ADD CONSTRAINT customer_credit_applications_authorization_reference_check CHECK (
                (final_settlement_id IS NULL AND authorization_reference='credits.apply')
                OR (final_settlement_id IS NOT NULL AND authorization_reference='financial.approve'));
        CREATE INDEX customer_credit_applications_final_settlement_idx
            ON app.customer_credit_applications(final_settlement_id) WHERE final_settlement_id IS NOT NULL;

        -- The id of the Credit application that a Customer Credit step of a FINAL_SETTLEMENT draft
        -- writes (step = its 1-based position in the draft's steps), so each step is written once.
        CREATE FUNCTION app.final_settlement_credit_application_id(p_draft uuid,p_step integer)
        RETURNS uuid LANGUAGE sql IMMUTABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT md5('final-settlement-credit-application:' || p_draft::text || ':' || p_step::text)::uuid
        $$;

        -- The source check of a Final Settlement Credit application (BR-CREDIT-006, BR-CREDIT-008,
        -- BR-SETTLE-004, BR-AUTH-010, DL-032). It runs before the existing Credit checks
        -- (customer_credit_applications_validate), which still run on the row. Shape and source
        -- mismatches are 23514; business state that can change (a closed Settlement, Deposit
        -- applications or Refunds already written) is 55000; a row without a human approver is 42501.
        CREATE FUNCTION app.assert_final_settlement_credit_application_source()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_settlement app.final_settlements%ROWTYPE; v_lease app.leases%ROWTYPE;
            v_draft uuid; v_step jsonb; v_target_lease uuid; v_target uuid; v_basis text;
        BEGIN
            -- Lock order of the other Settlement writers (8a, 8d): the Settlement row first.
            SELECT * INTO v_settlement FROM app.final_settlements WHERE id=NEW.final_settlement_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='23503'; END IF;
            IF v_settlement.closed_at IS NOT NULL THEN
                RAISE EXCEPTION 'A closed Final Settlement takes no new Credit application' USING ERRCODE='55000';
            END IF;
            -- As the Settlement's Deposit applications and Refunds (8a, 8d; review round 2).
            IF NEW.occurred_at<v_settlement.started_at THEN
                RAISE EXCEPTION 'A Final Settlement Credit application cannot precede its Final Settlement'
                    USING ERRCODE='23514'; END IF;
            -- BR-AUTH-010: a person confirms (the application checks financial.approve).
            IF NOT EXISTS(SELECT 1 FROM app.actor_identities identity
                WHERE identity.actor_id=NEW.actor_id AND identity.identity_kind='HUMAN')
                OR NEW.authorization_reference IS DISTINCT FROM 'financial.approve'
            THEN RAISE EXCEPTION 'A Final Settlement Credit application needs a human approver under financial.approve'
                USING ERRCODE='42501'; END IF;
            PERFORM app.assert_active_financial_actor(NEW.actor_id,v_settlement.property_id);
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_settlement.lease_id;
            IF NEW.target_kind='INVOICE' THEN
                SELECT invoice.lease_id INTO v_target_lease FROM app.invoices invoice WHERE invoice.id=NEW.invoice_id;
            ELSE
                SELECT invoice.lease_id INTO v_target_lease FROM app.late_payment_charges charge
                JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                WHERE charge.id=NEW.late_payment_charge_id;
            END IF;
            IF v_lease.status IS DISTINCT FROM 'TERMINATED' OR v_target_lease IS DISTINCT FROM v_lease.id THEN
                RAISE EXCEPTION 'The Credit target must be an obligation of the terminated Settlement Lease'
                    USING ERRCODE='23514'; END IF;
            -- DL-032 step 2 and BR-SETTLE-004: Customer Credit before any Deposit application or Refund.
            IF EXISTS(SELECT 1 FROM app.deposit_applications application
                    WHERE application.final_settlement_id=v_settlement.id)
                OR EXISTS(SELECT 1 FROM app.final_settlement_refund_details detail
                    WHERE detail.final_settlement_id=v_settlement.id)
            THEN RAISE EXCEPTION 'Customer Credit is applied before the Final Settlement Deposit applications and Refunds'
                USING ERRCODE='55000'; END IF;
            -- BR-AUTH-010: the row is the Customer Credit step its id names, of a FINAL_SETTLEMENT draft
            -- of this Settlement that is pending or confirmed by this approver.
            SELECT draft.id,step.value INTO v_draft,v_step
            FROM app.financial_drafts draft
            CROSS JOIN LATERAL jsonb_array_elements(draft.payload->'steps') WITH ORDINALITY step(value,ordinality)
            WHERE draft.kind='FINAL_SETTLEMENT' AND draft.property_id=v_settlement.property_id
              AND draft.payload->>'final_settlement_id'=v_settlement.id::text
              AND app.final_settlement_credit_application_id(draft.id,step.ordinality::integer)=NEW.id;
            v_target:=app.final_settlement_plan_id(v_step->'target_id')::uuid;
            -- BR-CREDIT-006 (owner answer 1 to Q-2026-10-05-29): the Customer's designation recorded as
            -- text; otherwise the Rent-first proposal on an Invoice with Rent or Service lines, the
            -- other applicable obligation on any other Invoice, and a direct Late-payment Charge.
            v_basis:=CASE WHEN jsonb_typeof(v_step->'customer_designation')='string' THEN 'CUSTOMER_DESIGNATED'
                WHEN v_step->>'target_kind'='LATE_PAYMENT_CHARGE' THEN 'NOT_APPLICABLE'
                WHEN EXISTS(SELECT 1 FROM app.invoice_lines line
                    WHERE line.invoice_id=NEW.invoice_id AND line.category IN ('RENT','SERVICE_CHARGES'))
                    THEN 'RENT_THEN_RECURRING_SERVICES_PROPOSAL'
                ELSE 'OTHER_APPLICABLE_OBLIGATION' END;
            IF v_draft IS NULL
                OR EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                    WHERE decision.draft_id=v_draft
                      AND (decision.decision<>'CONFIRMED' OR decision.decided_by<>NEW.actor_id))
                OR v_step->>'kind' IS DISTINCT FROM 'CUSTOMER_CREDIT'
                OR app.final_settlement_plan_id(v_step->'customer_credit_id') IS DISTINCT FROM NEW.customer_credit_id::text
                OR v_step->>'amount_usd_cents' IS DISTINCT FROM NEW.amount_usd_cents::text
                OR (v_step->>'target_kind'='INVOICE_LINE' AND (NEW.target_kind<>'INVOICE'
                    OR NOT EXISTS(SELECT 1 FROM app.invoice_lines line
                        WHERE line.id=v_target AND line.invoice_id=NEW.invoice_id)))
                OR (v_step->>'target_kind'='LATE_PAYMENT_CHARGE' AND (NEW.target_kind<>'LATE_PAYMENT_CHARGE'
                    OR NEW.late_payment_charge_id IS DISTINCT FROM v_target))
                OR COALESCE(v_step->>'target_kind','') NOT IN ('INVOICE_LINE','LATE_PAYMENT_CHARGE')
                OR NEW.within_invoice_basis IS DISTINCT FROM v_basis
                -- In parentheses: a bare CASE would end this condition early (PL/pgSQL).
                OR NEW.customer_designation_reference IS DISTINCT FROM
                    (CASE WHEN v_basis='CUSTOMER_DESIGNATED' THEN v_step->>'customer_designation' END)
            THEN RAISE EXCEPTION 'A Final Settlement Credit application must be a Credit step of a waiting or confirmed draft of this Settlement'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER a0_customer_credit_applications_final_settlement BEFORE INSERT
            ON app.customer_credit_applications FOR EACH ROW
            WHEN (NEW.final_settlement_id IS NOT NULL)
            EXECUTE FUNCTION app.assert_final_settlement_credit_application_source();

        -- BR-AUTH-010 at commit (as the Settlement Refunds, sub-slice 8d): a Final Settlement Credit
        -- application commits only with its draft confirmed under financial.approve by the same
        -- approver, in this transaction or before it, and it pays exactly the obligation of its step.
        CREATE FUNCTION app.assert_final_settlement_credit_application_confirmed()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_draft uuid; v_step jsonb; v_count integer;
            v_detail app.customer_credit_application_details%ROWTYPE;
        BEGIN
            SELECT draft.id,step.value INTO v_draft,v_step
            FROM app.final_settlements settlement
            JOIN app.financial_drafts draft ON draft.kind='FINAL_SETTLEMENT'
                AND draft.property_id=settlement.property_id
                AND draft.payload->>'final_settlement_id'=settlement.id::text
            CROSS JOIN LATERAL jsonb_array_elements(draft.payload->'steps') WITH ORDINALITY step(value,ordinality)
            WHERE settlement.id=NEW.final_settlement_id
              AND app.final_settlement_credit_application_id(draft.id,step.ordinality::integer)=NEW.id;
            IF v_draft IS NULL OR NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                WHERE decision.draft_id=v_draft AND decision.decision='CONFIRMED'
                  AND decision.authorization_reference='financial.approve'
                  AND decision.decided_by=NEW.actor_id)
            THEN RAISE EXCEPTION 'A Final Settlement Credit application needs its draft confirmed under financial.approve by the same approver'
                USING ERRCODE='42501'; END IF;
            SELECT count(*) INTO v_count FROM app.customer_credit_application_details
                WHERE customer_credit_application_id=NEW.id;
            SELECT * INTO v_detail FROM app.customer_credit_application_details
                WHERE customer_credit_application_id=NEW.id;
            IF v_count<>1 OR v_detail.applied_amount_usd_cents IS DISTINCT FROM NEW.amount_usd_cents
                OR (v_step->>'target_kind'='INVOICE_LINE' AND v_detail.invoice_line_id::text
                    IS DISTINCT FROM app.final_settlement_plan_id(v_step->'target_id'))
                OR (v_step->>'target_kind'='LATE_PAYMENT_CHARGE' AND v_detail.late_payment_charge_id::text
                    IS DISTINCT FROM app.final_settlement_plan_id(v_step->'target_id'))
            THEN RAISE EXCEPTION 'A Final Settlement Credit application pays exactly the obligation of its Credit step'
                USING ERRCODE='23514'; END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER customer_credit_applications_final_settlement_confirmed
            AFTER INSERT ON app.customer_credit_applications
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            WHEN (NEW.final_settlement_id IS NOT NULL)
            EXECUTE FUNCTION app.assert_final_settlement_credit_application_confirmed();

        -- Owner answer 3 to Q-2026-10-06-32: a Credit application the Settlement made is part of the
        -- closed Settlement (BR-SETTLE-012) and changes only through a post-settlement correction
        -- (BR-SETTLE-013, slice 10). It runs before the existing reversal checks and their locks, so
        -- every writer of a reversal (the one-call reversal and the credit Adjustment excess path)
        -- inherits it. P5S01 is the closed Settlement refusal of sub-slice 8e-1 (a conflict).
        CREATE FUNCTION app.refuse_final_settlement_credit_application_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF EXISTS(SELECT 1 FROM app.customer_credit_applications application
                WHERE application.id=NEW.credit_application_id AND application.final_settlement_id IS NOT NULL)
            THEN RAISE EXCEPTION 'A Final Settlement Credit application changes only through a post-settlement correction'
                USING ERRCODE='P5S01'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER a0_customer_credit_application_reversals_final_settlement BEFORE INSERT
            ON app.customer_credit_application_reversals FOR EACH ROW
            EXECUTE FUNCTION app.refuse_final_settlement_credit_application_reversal();

        -- The only writer of a Final Settlement Credit application: the Settlement confirm (8e-3)
        -- calls it with the approver, once for each Customer Credit step of the draft (p_step is the
        -- step's 1-based position), in the draft's order, after its decision and before any Deposit
        -- application or Refund; 8e-3 has already taken the locks of its plan notes (note 7 as
        -- amended by the 8e-2 notes: the steps' Payments and Credits, the Lease's Charges and
        -- Invoices, then the Settlement row). No role may call it.
        CREATE FUNCTION app.post_final_settlement_credit_application(p_property uuid,p_actor uuid,
            p_settlement uuid,p_draft uuid,p_step integer)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_settlement app.final_settlements%ROWTYPE; v_draft app.financial_drafts%ROWTYPE;
            v_step jsonb; v_id uuid; v_credit uuid; v_payment uuid; v_target uuid; v_invoice uuid;
            v_charge uuid; v_line app.invoice_lines%ROWTYPE; v_amount bigint; v_reference text;
            v_basis text; v_detail_basis text; v_proposal jsonb; v_at timestamptz;
        BEGIN
            SELECT * INTO v_settlement FROM app.final_settlements WHERE id=p_settlement FOR UPDATE;
            IF NOT FOUND OR v_settlement.property_id IS DISTINCT FROM p_property
            THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
            IF p_actor IS NULL OR p_draft IS NULL OR p_step IS NULL OR p_step<1
            THEN RAISE EXCEPTION 'Final Settlement Credit application input is invalid' USING ERRCODE='22023'; END IF;
            SELECT * INTO v_draft FROM app.financial_drafts
            WHERE id=p_draft AND property_id=p_property AND kind='FINAL_SETTLEMENT'
              AND payload->>'final_settlement_id'=p_settlement::text;
            IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement draft was not found' USING ERRCODE='P0002'; END IF;
            v_step:=v_draft.payload->'steps'->(p_step-1);
            v_credit:=app.final_settlement_plan_id(v_step->'customer_credit_id')::uuid;
            v_target:=app.final_settlement_plan_id(v_step->'target_id')::uuid;
            IF v_step->>'kind' IS DISTINCT FROM 'CUSTOMER_CREDIT' OR v_credit IS NULL OR v_target IS NULL
                OR jsonb_typeof(v_step->'amount_usd_cents') IS DISTINCT FROM 'number'
                OR (v_step->>'amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
            THEN RAISE EXCEPTION 'The draft step is not a Customer Credit step' USING ERRCODE='22023'; END IF;
            v_amount:=(v_step->>'amount_usd_cents')::bigint;
            v_reference:=CASE WHEN jsonb_typeof(v_step->'customer_designation')='string'
                THEN v_step->>'customer_designation' END;
            IF v_step->>'target_kind'='INVOICE_LINE' THEN
                SELECT * INTO v_line FROM app.invoice_lines WHERE id=v_target;
                IF NOT FOUND THEN RAISE EXCEPTION 'Credit target was not found' USING ERRCODE='P0002'; END IF;
                v_invoice:=v_line.invoice_id;
            ELSIF v_step->>'target_kind'='LATE_PAYMENT_CHARGE' THEN
                PERFORM 1 FROM app.late_payment_charges WHERE id=v_target;
                IF NOT FOUND THEN RAISE EXCEPTION 'Credit target was not found' USING ERRCODE='P0002'; END IF;
                v_charge:=v_target;
            ELSE RAISE EXCEPTION 'The draft step is not a Customer Credit step' USING ERRCODE='22023';
            END IF;
            SELECT source_payment_id INTO v_payment FROM app.customer_credits WHERE id=v_credit;
            IF NOT FOUND THEN RAISE EXCEPTION 'Credit not found' USING ERRCODE='P0002'; END IF;
            -- The locks of app.post_credit_application, in its order: the Payment, the Credit, the
            -- target and its lines.
            PERFORM app.serialize_payment_state(v_payment);
            PERFORM 1 FROM app.payments WHERE id=v_payment FOR UPDATE;
            PERFORM 1 FROM app.customer_credits WHERE id=v_credit FOR UPDATE;
            PERFORM app.lock_payment_allocation_target(CASE WHEN v_invoice IS NULL THEN 'LATE_PAYMENT_CHARGE'
                ELSE 'INVOICE' END,COALESCE(v_invoice,v_charge));
            PERFORM 1 FROM app.invoice_lines WHERE invoice_id=v_invoice ORDER BY id FOR UPDATE;
            -- Strictly later than every earlier event of the Credit and of the target (the existing
            -- chronology checks), also when steps follow each other within one microsecond.
            v_at:=GREATEST(clock_timestamp(),
                app.credit_latest_at(v_credit)+interval '1 microsecond',
                app.allocation_target_latest_at(CASE WHEN v_invoice IS NULL THEN 'LATE_PAYMENT_CHARGE'
                    ELSE 'INVOICE' END,COALESCE(v_invoice,v_charge))+interval '1 microsecond',
                (SELECT GREATEST(invoice.issued_at,invoice.updated_at) FROM app.invoices invoice
                    WHERE invoice.id=v_invoice));
            -- BR-CREDIT-006 (owner answer 1 to Q-2026-10-05-29).
            IF v_reference IS NOT NULL THEN
                v_basis:='CUSTOMER_DESIGNATED'; v_detail_basis:='CUSTOMER_DESIGNATED';
            ELSIF v_charge IS NOT NULL THEN
                v_basis:='NOT_APPLICABLE'; v_detail_basis:='DIRECT_LATE_PAYMENT_CHARGE';
            ELSIF EXISTS(SELECT 1 FROM app.invoice_lines line
                WHERE line.invoice_id=v_invoice AND line.category IN ('RENT','SERVICE_CHARGES'))
            THEN
                -- The existing Credit proposal for this amount must pay exactly the step's line.
                v_basis:='RENT_THEN_RECURRING_SERVICES_PROPOSAL';
                v_proposal:=app.credit_application_proposal(p_property,v_credit,v_invoice,v_amount,v_at);
                IF (v_proposal->>'amount_usd_cents')::bigint IS DISTINCT FROM v_amount
                    OR jsonb_array_length(v_proposal->'details')<>1
                    OR v_proposal->'details'->0->>'invoice_line_id' IS DISTINCT FROM v_target::text
                THEN RAISE EXCEPTION 'Credit on an Invoice with Rent or Service lines follows the Rent-first proposal unless the Customer designated the line'
                    USING ERRCODE='23514'; END IF;
                v_detail_basis:=v_proposal->'details'->0->>'attribution_basis';
            ELSE
                v_basis:='OTHER_APPLICABLE_OBLIGATION'; v_detail_basis:='OTHER_CONFIRMED';
            END IF;
            v_id:=app.final_settlement_credit_application_id(p_draft,p_step);
            -- As in app.post_credit_application, the header's checks wait for its detail, also after an
            -- earlier SET CONSTRAINTS ALL IMMEDIATE in this transaction. Only this writer's own checks
            -- are named (as the 8d Refund writer does, review round 1), and they are never set
            -- IMMEDIATE again here, so the other constraints of the confirm transaction keep their mode.
            SET CONSTRAINTS app.customer_credit_applications_complete,
                app.customer_credit_application_details_complete,
                app.customer_credit_applications_credit_history,
                app.customer_credit_applications_final_settlement_confirmed DEFERRED;
            INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,invoice_id,
                late_payment_charge_id,final_settlement_id,amount_usd_cents,within_invoice_basis,
                customer_designation_reference,proposal_generated_at,proposal_trace,occurred_at,actor_id,
                authorization_reference)
            VALUES(v_id,v_credit,CASE WHEN v_invoice IS NULL THEN 'LATE_PAYMENT_CHARGE' ELSE 'INVOICE' END,
                v_invoice,v_charge,p_settlement,v_amount,v_basis,v_reference,
                CASE WHEN v_proposal IS NOT NULL THEN v_at END,v_proposal,v_at,p_actor,'financial.approve');
            INSERT INTO app.customer_credit_application_details(id,customer_credit_application_id,
                invoice_line_id,late_payment_charge_id,obligation_kind,invoice_line_category_snapshot,
                proposed_amount_usd_cents,applied_amount_usd_cents,attribution_basis,detail_sequence,
                calculation_trace)
            VALUES(gen_random_uuid(),v_id,v_line.id,v_charge,
                CASE WHEN v_invoice IS NULL THEN 'LATE_PAYMENT_CHARGE' ELSE 'INVOICE_LINE' END,v_line.category,
                CASE WHEN v_proposal IS NOT NULL THEN v_amount END,v_amount,v_detail_basis,1,
                jsonb_build_object('final_settlement_id',p_settlement,'draft_id',p_draft,'step_sequence',p_step,
                    'confirmed_detail',v_step,'designation_reference',v_reference));
            IF v_invoice IS NOT NULL THEN PERFORM app.refresh_allocated_invoice(v_invoice,p_actor,true); END IF;
            RETURN jsonb_build_object('id',v_id,'final_settlement_id',p_settlement,'draft_id',p_draft,
                'step_sequence',p_step,'customer_credit_id',v_credit,
                'target_kind',CASE WHEN v_invoice IS NULL THEN 'LATE_PAYMENT_CHARGE' ELSE 'INVOICE' END,
                'invoice_id',v_invoice,'invoice_line_id',v_line.id,'late_payment_charge_id',v_charge,
                'amount_usd_cents',v_amount,'within_invoice_basis',v_basis,
                'customer_designation_reference',v_reference,'occurred_at',v_at);
        END $$;
    """)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Final Settlement Credit application migration is forward-only")
