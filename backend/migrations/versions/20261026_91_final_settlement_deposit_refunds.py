# ruff: noqa: E501
"""Final Settlement Deposit Refunds (V1-056 sub-slice 8d).

BR-DEP-025, BR-REFUND-007, BR-REFUND-014, BR-REFUND-015, BR-SETTLE-008, BR-AUTH-010, DL-032;
owner answer to choice (4a) of sub-slice 8c (2026-10-05) and owner answer 3 to Q-2026-10-05-20.

- Owner answer to choice (4a): app.final_settlement_plan_result also refuses a plan in which the
  remaining Pet Deposit (DL-032 step 5) pays debt while a Security Deposit on the DL-032 path
  still holds money, whether staff or the Customer chose it. The draft recorder and the confirm
  (8e) both call this check. This refuses plans the 8c check accepted; the owner approved it.
- app.final_settlement_refund_details (append-only) links a Refund of a Lease Security or Pet
  Deposit to its Final Settlement (docs/004 DB-REFUND-001) and records its method, reference
  note, the Signers' written agreement when another Signer is paid, and the FINAL_SETTLEMENT
  draft it comes from; one Refund per Deposit per Settlement. The link is not a new app.refunds
  column, because every Refund reader returns the whole Refund row and the frontend checks its
  keys exactly; app.refunds keeps its columns. Its source-context check is relaxed so a Deposit
  Refund may have neither a Reservation event nor a Pet Refund review; the Refund source trigger
  then requires the Settlement link. Every earlier row keeps its context.
- app.post_final_settlement_deposit_refund is the only writer and is internal (no role may call
  it); the Settlement confirm (8e) calls it with the financial.approve reference. A deferred check
  (app.assert_final_settlement_refund_confirmed) lets such a Refund commit only with its draft
  confirmed by the same approver under financial.approve. The Refund
  source check app.assert_final_settlement_refund_source runs for every writer: an open
  Settlement of a terminated Lease, a Deposit of that Lease on the DL-032 path paid to the
  Primary Tenant or to another signed Signer with the agreement, an active method, a Refund step
  of a FINAL_SETTLEMENT draft of that Settlement that is pending or confirmed by the same
  approver, an amount within the held Deposit, no waiting receipt reversal or forfeiture draft of
  the Deposit (the owner's 8r rule, answer to Q-2026-10-05-31), and no open debt of the Lease that
  a Deposit could pay (owner answer 3 to Q-2026-10-05-20).
- The general Refund audit books a Settlement Refund like a Pet Deposit Refund (the Deposit's
  Property and Lease). A Settlement Refund is not corrected with the one-call Refund corrections;
  that waits for the post-settlement corrections (slice 10). A Deposit application of a
  Settlement is refused once that Settlement has a Refund (BR-SETTLE-008: applications first).

Additive and relaxing apart from the owner-approved (4a) check; the new refusals in the patched
Refund correction and Deposit application checks see records no writer could create before.
"""

from alembic import op
from sqlalchemy import text

revision = "20261026_91"
down_revision = "20261025_90"
branch_labels = None
depends_on = None

PLAN = "app.final_settlement_plan_result(uuid,uuid,uuid,jsonb)"
SOURCE = "app.validate_general_refund_source()"
AUDIT = "app.audit_general_refund_event()"
CORRECTION = "app.validate_general_refund_correction()"
CORRECTABLE = "app.require_correctable_usd_refund(uuid,uuid)"
APPLICATION = "app.validate_deposit_application()"
INTERNAL = (
    "app.assert_final_settlement_refund_source(app.refunds)",
    "app.post_final_settlement_deposit_refund(uuid,uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid,text,text,text)",
    "app.reject_final_settlement_refund_detail_mutation()",
    "app.assert_final_settlement_refund_confirmed()",
)

PLAN_DECLARE_BEFORE = "            v_method text; v_recipient text;\n"
PLAN_DECLARE_AFTER = "            v_method text; v_recipient text; v_security_at_five bigint;\n"
PLAN_STEP_BEFORE = "                        v_step_five:=v_step_five OR v_step=5;\n"
PLAN_STEP_AFTER = (
    "                        v_step_five:=v_step_five OR v_step=5;\n"
    "                        -- What the Security Deposit still holds when step 5 starts (owner answer\n"
    "                        -- to choice (4a) of sub-slice 8c; sub-slice 8d).\n"
    "                        IF v_step=5 AND v_security_at_five IS NULL THEN\n"
    "                            SELECT COALESCE(sum(item.value::bigint),0) INTO v_security_at_five\n"
    "                            FROM jsonb_each_text(v_left) item WHERE v_type->>item.key='SECURITY';\n"
    "                        END IF;\n"
)
PLAN_CHECK_BEFORE = (
    "            THEN RAISE EXCEPTION 'No Deposit Refund while the Lease still has open debt that the Deposit could pay'\n"
    "                USING ERRCODE='55000'; END IF;\n"
)
PLAN_CHECK_AFTER = (
    PLAN_CHECK_BEFORE
    + "            -- Owner answer to choice (4a) of sub-slice 8c (2026-10-05): the remaining Pet Deposit pays\n"
    "            -- only debt still open after the Security Deposit has been used, also when the Customer\n"
    "            -- chooses it. A Security Deposit that still holds money at step 5 could pay that debt.\n"
    "            IF v_security_at_five>0 THEN\n"
    "                RAISE EXCEPTION 'The remaining Pet Deposit pays only debt still open after the Security Deposit has been used'\n"
    "                    USING ERRCODE='55000'; END IF;\n"
)

SOURCE_BEFORE = (
    "            IF NEW.pet_refund_review_id IS NOT NULL THEN\n"
    "                PERFORM app.assert_pet_refund_source(NEW);\n"
)
SOURCE_AFTER = (
    "            -- A Deposit Refund with neither a Reservation event nor a Pet Refund review is a Final\n"
    "            -- Settlement Deposit Refund (BR-REFUND-007; V1-056 sub-slice 8d).\n"
    "            IF NEW.source_deposit_id IS NOT NULL AND NEW.pet_refund_review_id IS NULL THEN\n"
    "                PERFORM app.assert_final_settlement_refund_source(NEW);\n"
    "                RETURN NEW;\n"
    "            END IF;\n" + SOURCE_BEFORE
)
AUDIT_BEFORE = (
    "            IF v_refund.pet_refund_review_id IS NOT NULL THEN\n"
    "                SELECT app.deposit_property_id(id),lease_id INTO STRICT v_property,v_lease\n"
)
AUDIT_AFTER = (
    "            -- A Pet Deposit Refund or a Final Settlement Deposit Refund (sub-slice 8d).\n"
    "            IF v_refund.source_deposit_id IS NOT NULL THEN\n"
    "                SELECT app.deposit_property_id(id),lease_id INTO STRICT v_property,v_lease\n"
)
AUDIT_STATE_BEFORE = "                    'source_customer_credit_id',v_refund.source_customer_credit_id,'source_event',to_jsonb(NEW)),\n"
AUDIT_STATE_AFTER = (
    "                    'source_customer_credit_id',v_refund.source_customer_credit_id,'source_event',to_jsonb(NEW))\n"
    "                    -- Only a Final Settlement Refund gains this key (sub-slice 8d).\n"
    "                    ||COALESCE((SELECT jsonb_build_object('final_settlement_id',detail.final_settlement_id)\n"
    "                        FROM app.final_settlement_refund_details detail WHERE detail.refund_id=v_refund.id),\n"
    "                        '{}'::jsonb),\n"
)
CORRECTION_BEFORE = (
    "            IF v_refund.pet_refund_review_id IS NOT NULL THEN\n"
    "                PERFORM app.serialize_deposit_state(v_refund.source_deposit_id);\n"
)
CORRECTION_AFTER = (
    "            -- A Final Settlement Refund is corrected only through a post-settlement correction\n"
    "            -- (BR-SETTLE-013; slice 10), not a one-call Refund correction (sub-slice 8d).\n"
    "            IF v_refund.source_deposit_id IS NOT NULL AND v_refund.pet_refund_review_id IS NULL THEN\n"
    "                RAISE EXCEPTION 'A Final Settlement Refund is corrected only through a post-settlement correction'\n"
    "                    USING ERRCODE='23514'; END IF;\n" + CORRECTION_BEFORE
)
CORRECTABLE_BEFORE = "            IF v_refund.source_lifecycle_event_id IS NOT NULL OR v_refund.refund_currency<>'USD' THEN\n"
CORRECTABLE_AFTER = (
    "            -- A Final Settlement Deposit Refund waits for the post-settlement corrections (8d).\n"
    "            IF v_refund.source_lifecycle_event_id IS NOT NULL OR v_refund.refund_currency<>'USD'\n"
    "                OR (v_refund.source_deposit_id IS NOT NULL AND v_refund.pet_refund_review_id IS NULL) THEN\n"
)
APPLICATION_BEFORE = (
    "            IF v_settlement.closed_at IS NOT NULL THEN\n"
    "                RAISE EXCEPTION 'A closed Final Settlement takes no new Deposit application' USING ERRCODE='55000'; END IF;\n"
)
APPLICATION_AFTER = (
    APPLICATION_BEFORE
    + "            -- BR-SETTLE-008: every Deposit application is recorded before the remaining Deposit\n"
    "            -- balances are refunded (sub-slice 8d).\n"
    "            IF EXISTS(SELECT 1 FROM app.final_settlement_refund_details detail\n"
    "                WHERE detail.final_settlement_id=NEW.final_settlement_id) THEN\n"
    "                RAISE EXCEPTION 'Deposit applications are recorded before the Final Settlement Refunds'\n"
    "                    USING ERRCODE='55000'; END IF;\n"
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
            raise RuntimeError(f"Final Settlement Refund source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    # Owner answer to choice (4a) first: the plan check the draft and the confirm (8e) share.
    _patch(
        PLAN,
        (
            (PLAN_DECLARE_BEFORE, PLAN_DECLARE_AFTER),
            (PLAN_STEP_BEFORE, PLAN_STEP_AFTER),
            (PLAN_CHECK_BEFORE, PLAN_CHECK_AFTER),
        ),
    )
    op.execute("""
        -- Relaxed: a Deposit Refund may have neither a Reservation event nor a Pet Refund review; the
        -- Refund source trigger then requires its Final Settlement link (below). Only a Deposit
        -- Refund has a context, and at most one.
        ALTER TABLE app.refunds
            DROP CONSTRAINT refund_source_context,
            ADD CONSTRAINT refund_source_context CHECK (
                num_nonnulls(source_lifecycle_event_id,pet_refund_review_id)<=1
                AND (source_deposit_id IS NOT NULL
                    OR num_nonnulls(source_lifecycle_event_id,pet_refund_review_id)=0));

        -- The Final Settlement link, method, reference note and Signers' agreement of each Final
        -- Settlement Deposit Refund (BR-REFUND-007, BR-REFUND-014, BR-REFUND-015), with the
        -- FINAL_SETTLEMENT draft it comes from. Written before its Refund row (deferred key) so
        -- the Refund source check can read it.
        CREATE TABLE app.final_settlement_refund_details (
            refund_id uuid PRIMARY KEY REFERENCES app.refunds(id) ON DELETE RESTRICT
                DEFERRABLE INITIALLY DEFERRED,
            final_settlement_id uuid NOT NULL REFERENCES app.final_settlements(id) ON DELETE RESTRICT,
            deposit_id uuid NOT NULL REFERENCES app.deposits(id) ON DELETE RESTRICT,
            draft_id uuid NOT NULL REFERENCES app.financial_drafts(id) ON DELETE RESTRICT,
            refund_method_id uuid NOT NULL REFERENCES app.refund_methods(id) ON DELETE RESTRICT,
            reference_note text NOT NULL
                CHECK (reference_note=btrim(reference_note) AND length(reference_note) BETWEEN 1 AND 500),
            signer_agreement text
                CHECK (signer_agreement IS NULL
                    OR (signer_agreement=btrim(signer_agreement) AND length(signer_agreement) BETWEEN 1 AND 2000)),
            recorded_at timestamptz NOT NULL CHECK (isfinite(recorded_at)),
            -- BR-SETTLE-008 and BR-REFUND-007: each Deposit is refunded separately, once per Settlement.
            CONSTRAINT final_settlement_refund_once_per_deposit UNIQUE (final_settlement_id,deposit_id)
        );
        CREATE INDEX final_settlement_refund_details_draft_idx
            ON app.final_settlement_refund_details(draft_id);
        COMMENT ON TABLE app.final_settlement_refund_details IS
            'Append-only method, reference note and Signer agreement of Final Settlement Deposit Refunds (BR-REFUND-007, BR-REFUND-014, BR-REFUND-015); written only by the Settlement confirm';
        CREATE FUNCTION app.reject_final_settlement_refund_detail_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Final Settlement Refund details are append-only' USING ERRCODE='55000';
        END $$;
        CREATE TRIGGER final_settlement_refund_details_immutable BEFORE UPDATE OR DELETE
            ON app.final_settlement_refund_details FOR EACH ROW
            EXECUTE FUNCTION app.reject_final_settlement_refund_detail_mutation();
        CREATE TRIGGER final_settlement_refund_details_no_truncate BEFORE TRUNCATE
            ON app.final_settlement_refund_details FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_final_settlement_refund_detail_mutation();
        -- BR-AUTH-010 at commit: a Final Settlement Refund commits only with its draft confirmed by
        -- the same approver under financial.approve, in this transaction or before it (review
        -- round 1). The source check below also refuses a rejected or withdrawn draft at once.
        CREATE FUNCTION app.assert_final_settlement_refund_confirmed()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM app.refunds refund
                JOIN app.financial_draft_decisions decision ON decision.draft_id=NEW.draft_id
                WHERE refund.id=NEW.refund_id AND decision.decision='CONFIRMED'
                  AND decision.authorization_reference='financial.approve'
                  AND decision.decided_by=refund.processed_by)
            THEN RAISE EXCEPTION 'A Final Settlement Refund needs its draft confirmed under financial.approve by the same approver'
                USING ERRCODE='42501'; END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER final_settlement_refund_details_confirmed
            AFTER INSERT ON app.final_settlement_refund_details
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION app.assert_final_settlement_refund_confirmed();

        -- The Refund source check of a Final Settlement Deposit Refund (BR-DEP-025, BR-REFUND-007,
        -- BR-REFUND-014, BR-REFUND-015, BR-SETTLE-008, BR-AUTH-010). Called by the general Refund
        -- source trigger, so every writer inherits it. Shape and source mismatches are 23514;
        -- business state that can change (a closed Settlement, an inactive method, a waiting
        -- receipt reversal or forfeiture draft, open debt) is
        -- 55000; a Refund without a human approver is 42501.
        CREATE FUNCTION app.assert_final_settlement_refund_source(p_refund app.refunds)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_settlement app.final_settlements%ROWTYPE; v_lease app.leases%ROWTYPE;
            v_deposit app.deposits%ROWTYPE; v_detail app.final_settlement_refund_details%ROWTYPE;
            v_draft app.financial_drafts%ROWTYPE; v_ground text; v_staff_pet_step boolean;
            v_open bigint; v_pet_open bigint;
        BEGIN
            -- The Settlement link is recorded first (deferred key); without it a Deposit Refund has
            -- no source context.
            SELECT * INTO v_detail FROM app.final_settlement_refund_details WHERE refund_id=p_refund.id;
            IF NOT FOUND OR v_detail.deposit_id IS DISTINCT FROM p_refund.source_deposit_id THEN
                RAISE EXCEPTION 'A Deposit Refund needs its Reservation, Pet Refund review or Final Settlement source'
                    USING ERRCODE='23514'; END IF;
            -- Lock order of the Deposit applications (8a): the Settlement, then the Deposit.
            SELECT * INTO v_settlement FROM app.final_settlements
            WHERE id=v_detail.final_settlement_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='23503'; END IF;
            IF v_settlement.closed_at IS NOT NULL THEN
                RAISE EXCEPTION 'A closed Final Settlement takes no new Refund' USING ERRCODE='55000'; END IF;
            -- BR-AUTH-010: a person confirms (the application checks financial.approve).
            IF NOT EXISTS(SELECT 1 FROM app.actor_identities identity
                WHERE identity.actor_id=p_refund.processed_by AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'A Final Settlement Refund needs a human approver' USING ERRCODE='42501'; END IF;
            PERFORM app.assert_active_financial_actor(p_refund.processed_by,NULL);
            PERFORM app.assert_active_financial_actor(p_refund.processed_by,v_settlement.property_id);
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_settlement.lease_id;
            SELECT * INTO v_deposit FROM app.deposits WHERE id=p_refund.source_deposit_id;
            IF NOT FOUND OR v_deposit.lease_id IS DISTINCT FROM v_settlement.lease_id
                OR v_deposit.deposit_type NOT IN ('SECURITY','PET')
                OR v_deposit.customer_id IS DISTINCT FROM v_lease.primary_tenant_id
                OR v_lease.status IS DISTINCT FROM 'TERMINATED'
            THEN RAISE EXCEPTION 'The Refund source must be a Deposit of the terminated Settlement Lease'
                USING ERRCODE='23514'; END IF;
            -- The per-Deposit lock of the forfeiture, forfeiture reversal and receipt reversal draft
            -- recorders, then the Deposit row (their order).
            PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || v_deposit.id::text,0));
            PERFORM app.serialize_deposit_state(v_deposit.id);
            -- A kept Deposit, or one waiting for its forfeiture, is never refunded (BR-DEP-026).
            IF app.lease_deposit_settlement_path(v_settlement.property_id,v_deposit.id)->>'path'
                IS DISTINCT FROM 'DL_032'
            THEN RAISE EXCEPTION 'Only a Deposit that follows DL-032 is refunded at Final Settlement'
                USING ERRCODE='23514'; END IF;
            -- The owner's 8r rule (answer to Q-2026-10-05-31): no Refund while a Deposit receipt
            -- reversal draft or a forfeiture (or forfeiture reversal) draft waits for this Deposit,
            -- also when it was recorded after the Settlement draft was confirmed.
            IF EXISTS(SELECT 1 FROM app.financial_drafts draft
                WHERE draft.kind='DEPOSIT_FORFEITURE' AND draft.payload->>'deposit_id'=v_deposit.id::text
                  AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                      WHERE decision.draft_id=draft.id))
            THEN RAISE EXCEPTION 'A Deposit receipt reversal or forfeiture draft for this Deposit is waiting'
                USING ERRCODE='55000'; END IF;
            -- BR-REFUND-014: an active Refund method.
            PERFORM 1 FROM app.refund_methods WHERE id=v_detail.refund_method_id AND active FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
            -- BR-REFUND-015: the Primary Tenant (the Deposit owner), or another signed Signer of the
            -- Lease with the written agreement of all Signers.
            IF p_refund.recipient_customer_id=v_deposit.customer_id THEN
                IF v_detail.signer_agreement IS NOT NULL THEN
                    RAISE EXCEPTION 'The Primary Tenant needs no Signer agreement' USING ERRCODE='23514'; END IF;
            ELSIF v_detail.signer_agreement IS NULL OR NOT EXISTS(SELECT 1 FROM app.lease_signers signer
                WHERE signer.lease_id=v_lease.id AND signer.customer_id=p_refund.recipient_customer_id
                  AND signer.signed_at IS NOT NULL)
            THEN RAISE EXCEPTION 'A Refund to another Signer needs a signed Signer and the written agreement of all Signers'
                USING ERRCODE='23514'; END IF;
            -- BR-AUTH-010: the Refund is a Refund step of a FINAL_SETTLEMENT draft of this Settlement,
            -- exactly as prepared, and that draft is pending or confirmed by this approver.
            SELECT * INTO v_draft FROM app.financial_drafts WHERE id=v_detail.draft_id;
            IF NOT FOUND OR v_draft.kind<>'FINAL_SETTLEMENT' OR v_draft.property_id<>v_settlement.property_id
                OR v_draft.payload->>'final_settlement_id' IS DISTINCT FROM v_settlement.id::text
                OR EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                    WHERE decision.draft_id=v_draft.id
                      AND (decision.decision<>'CONFIRMED' OR decision.decided_by<>p_refund.processed_by))
                OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v_draft.payload->'steps') step
                    WHERE step->>'kind'='DEPOSIT_REFUNDS'
                      AND app.final_settlement_plan_id(step->'deposit_id')=v_deposit.id::text
                      AND step->>'amount_usd_cents'=p_refund.usd_accounting_value_cents::text
                      AND app.final_settlement_plan_id(step->'recipient_customer_id')=p_refund.recipient_customer_id::text
                      AND app.final_settlement_plan_id(step->'refund_method_id')=v_detail.refund_method_id::text
                      AND step->>'reference_note'=v_detail.reference_note
                      AND step->>'signer_agreement' IS NOT DISTINCT FROM v_detail.signer_agreement)
            THEN RAISE EXCEPTION 'A Final Settlement Refund must be a Refund step of a waiting or confirmed draft of this Settlement'
                USING ERRCODE='23514'; END IF;
            IF p_refund.usd_accounting_value_cents NOT BETWEEN 1 AND 9000000000000000
                OR p_refund.usd_accounting_value_cents>app.deposit_held_value_at(v_deposit.id,'infinity')
                OR NOT isfinite(p_refund.processed_at) OR p_refund.processed_at<v_settlement.started_at
                OR p_refund.processed_at<=COALESCE(app.deposit_balance_latest_at(v_deposit.id),'-infinity')
                OR p_refund.processed_at>clock_timestamp()+interval '5 seconds'
                OR app.lease_notice_text_valid(p_refund.reason,1000) IS NOT TRUE
                OR p_refund.authorization_reference IS DISTINCT FROM 'financial.approve'
            THEN RAISE EXCEPTION 'Final Settlement Refund amount, authorization or chronology is invalid'
                USING ERRCODE='23514'; END IF;
            -- Owner answer 3 to Q-2026-10-05-20 and BR-SETTLE-008: no Refund while the Lease still has
            -- open debt that a Deposit could pay. The open debt is read as the preview reads it: every
            -- issued, non-VOID Invoice of the Lease and its Late-payment Charges. A Security Deposit may
            -- pay any of it; the Pet Deposit pays pet damage first and other debt by the staff step
            -- outside the three BR-DEP-027 terminations; at those terminations, without the
            -- Customer's choice, its rest is refunded and the debt stays (Q-2026-10-05-21).
            SELECT COALESCE(sum(line_value.amount),0),
                COALESCE(sum(line_value.amount) FILTER (WHERE app.invoice_line_is_pet_damage(line.id,v_lease.id)),0)
            INTO v_open,v_pet_open
            FROM app.invoices invoice JOIN app.invoice_lines line ON line.invoice_id=invoice.id
            CROSS JOIN LATERAL (SELECT app.invoice_line_outstanding(line.id) AS amount) line_value
            WHERE invoice.lease_id=v_lease.id AND invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID')
                AND line_value.amount>0;
            v_open:=v_open+COALESCE((SELECT sum(position.remaining_balance_usd_cents)
                FROM app.late_payment_charges charge
                JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                JOIN app.late_payment_charge_financial_position position
                    ON position.late_payment_charge_id=charge.id
                WHERE invoice.lease_id=v_lease.id AND position.remaining_balance_usd_cents>0),0);
            v_ground:=app.lease_termination_forfeiture_rule(v_settlement.property_id,v_lease.id,'SECURITY');
            v_staff_pet_step:=v_ground IS NULL OR v_ground NOT IN ('BR-LEASE-005','BR-LEASE-025','BR-LEASE-028');
            IF (v_deposit.deposit_type='PET' AND v_pet_open>0)
                OR (v_open>0 AND (v_deposit.deposit_type='SECURITY' OR v_staff_pet_step
                    OR EXISTS(SELECT 1 FROM app.deposits other
                        WHERE other.lease_id=v_lease.id AND other.deposit_type='SECURITY' AND other.id<>v_deposit.id
                          AND app.deposit_held_value_at(other.id,'infinity')>0
                          AND app.lease_deposit_settlement_path(v_settlement.property_id,other.id)->>'path'='DL_032')))
            THEN RAISE EXCEPTION 'No Deposit Refund while the Lease still has open debt that a Deposit could pay'
                USING ERRCODE='55000'; END IF;
        END $$;

        -- The only writer of a Final Settlement Deposit Refund: the Settlement confirm (8e) calls it
        -- with the approver after the Deposit applications. No role may call it.
        CREATE FUNCTION app.post_final_settlement_deposit_refund(p_property uuid,p_actor uuid,
            p_settlement uuid,p_draft uuid,p_refund uuid,p_deposit uuid,p_amount bigint,p_recipient uuid,
            p_refund_method uuid,p_reference_note text,p_signer_agreement text,p_reason text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_settlement app.final_settlements%ROWTYPE; v_at timestamptz;
        BEGIN
            -- Lock order of the Deposit applications (8a): the Settlement, then the Deposit (its
            -- draft lock, then its row), before the details row takes its key locks (review round 1).
            SELECT * INTO v_settlement FROM app.final_settlements WHERE id=p_settlement FOR UPDATE;
            IF NOT FOUND OR v_settlement.property_id IS DISTINCT FROM p_property
            THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
            IF p_refund IS NULL OR p_refund='00000000-0000-0000-0000-000000000000' OR p_draft IS NULL
                OR p_deposit IS NULL OR p_recipient IS NULL OR p_refund_method IS NULL OR p_amount IS NULL
                OR p_actor IS NULL OR p_reason IS NULL
            THEN RAISE EXCEPTION 'Final Settlement Refund input is invalid' USING ERRCODE='22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || p_deposit::text,0));
            PERFORM app.serialize_deposit_state(p_deposit);
            -- Both checks of the details row wait for commit, even after an earlier
            -- SET CONSTRAINTS ALL IMMEDIATE in this transaction (for example by
            -- app.post_credit_application); this only moves them back to commit (review round 2).
            SET CONSTRAINTS app.final_settlement_refund_details_refund_id_fkey,
                app.final_settlement_refund_details_confirmed DEFERRED;
            v_at:=clock_timestamp();
            -- The details first (deferred key), so the Refund source check reads them.
            INSERT INTO app.final_settlement_refund_details(refund_id,final_settlement_id,deposit_id,draft_id,
                refund_method_id,reference_note,signer_agreement,recorded_at)
            VALUES(p_refund,p_settlement,p_deposit,p_draft,p_refund_method,p_reference_note,
                p_signer_agreement,v_at);
            INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_deposit_id,
                usd_accounting_value_cents,refund_currency,refund_amount_minor,reason,processed_at,
                processed_by,authorization_reference)
            VALUES(p_refund,'REF-'||p_refund::text,p_recipient,p_deposit,p_amount,'USD',p_amount,
                p_reason,v_at,p_actor,'financial.approve');
            RETURN jsonb_build_object('refund_id',p_refund,'refund_number','REF-'||p_refund::text,
                'final_settlement_id',p_settlement,'deposit_id',p_deposit,'draft_id',p_draft,
                'recipient_customer_id',p_recipient,'amount_usd_cents',p_amount,
                'refund_method_id',p_refund_method,'reference_note',p_reference_note,
                'signer_agreement',p_signer_agreement,'processed_at',v_at);
        END $$;
    """)
    _patch(SOURCE, ((SOURCE_BEFORE, SOURCE_AFTER),))
    _patch(AUDIT, ((AUDIT_BEFORE, AUDIT_AFTER), (AUDIT_STATE_BEFORE, AUDIT_STATE_AFTER)))
    _patch(CORRECTION, ((CORRECTION_BEFORE, CORRECTION_AFTER),))
    _patch(CORRECTABLE, ((CORRECTABLE_BEFORE, CORRECTABLE_AFTER),))
    _patch(APPLICATION, ((APPLICATION_BEFORE, APPLICATION_AFTER),))
    op.execute(
        "REVOKE ALL ON TABLE app.final_settlement_refund_details "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Final Settlement Refund migration is forward-only")
