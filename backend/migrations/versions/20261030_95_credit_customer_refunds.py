# ruff: noqa: E501
"""Credit Refund to the Invoice Customer who is not the payer (V1-056 sub-slice 8f).

BR-CREDIT-014, BR-AUTH-010, BR-REFUND-002, BR-REFUND-003, BR-REFUND-009, BR-REFUND-011,
BR-REFUND-014, BR-PAY-042; owner answer to Q-2026-10-05-19.

- A Customer Credit that a credit Adjustment released (app.invoice_credit_excess_releases) belongs
  to the Customer named on the Invoice, also when another person paid: a third-party Payment
  (migration 67) or a wrong-Unit move to another Customer (slice 7). Until now no Refund could pay
  such a Credit, because the Refund source check pays a Credit Refund only to a recipient who is
  both the Credit's Customer and the Payment's payer.
- New REFUND draft variant CREDIT_CUSTOMER, recorded under refunds.create by
  app.record_credit_customer_refund_draft (financial role) for such a Credit only (P5206
  otherwise), with a Refund method, a reference note and the Credit's Customer as recipient. The
  payload keeps source_kind CREDIT and source_id, so the existing draft readers and the Final
  Settlement preview's pending-draft check see it unchanged.
- app.confirm_refund_draft (financial.approve) gains the variant and calls the internal writer
  app.post_credit_customer_refund (no grant): the Payment then Credit lock of every Credit Refund,
  the Credit checked again, the amount within the available Credit (stale otherwise, P5202, the
  draft stays pending), the Refund paid to the Credit's Customer with processed_by the approver
  and authorization_reference refunds.create (as every confirmed Refund draft), the replay row;
  the method and note go to app.refund_draft_details as for the other variants.
- The Refund source check is relaxed for such a Credit only: the recipient is still the Credit's
  Customer, and the payer rule is lifted only while a matching CREDIT_CUSTOMER draft is pending or
  confirmed by the same approver. A deferred check lets such a Refund commit only with that draft
  CONFIRMED under financial.approve by the Refund's approver and its details row (as sub-slices
  8d and 8e-2).

Additive and relaxing: the relaxed check accepts every Refund it accepted before, and the new
refusals see records no writer could create before.
"""

from alembic import op
from sqlalchemy import text

revision = "20261030_95"
down_revision = "20261029_94"
branch_labels = None
depends_on = None

RECORD = "app.record_credit_customer_refund_draft(uuid,uuid,uuid,uuid,bigint,text,uuid,text,text)"
INTERNAL = (
    "app.credit_customer_refund_basis(uuid)",
    "app.credit_customer_refund_id(uuid)",
    "app.credit_customer_refund_draft(app.refunds)",
    "app.credit_customer_refund_allowed(app.refunds)",
    "app.assert_credit_customer_refund_confirmed()",
    "app.post_credit_customer_refund(uuid,uuid,uuid)",
)
CONFIRM = "app.confirm_refund_draft(uuid,uuid,uuid,text)"
SOURCE = "app.validate_general_refund_source()"

CONFIRM_VARIANTS_BEFORE = "                OR v_draft.payload->>'variant' NOT IN ('USD','PET')\n"
CONFIRM_VARIANTS_AFTER = (
    "                OR v_draft.payload->>'variant' NOT IN ('USD','PET','CREDIT_CUSTOMER')\n"
)
CONFIRM_BRANCH_BEFORE = (
    "            IF v_draft.payload->>'variant' = 'USD' THEN\n"
    "                -- A draft whose amount is no longer available is stale; it stays pending.\n"
)
CONFIRM_BRANCH_AFTER = (
    "            IF v_draft.payload->>'variant' = 'CREDIT_CUSTOMER' THEN\n"
    "                -- BR-CREDIT-014 (V1-056 sub-slice 8f): a Credit that a credit Adjustment released to\n"
    "                -- a Customer other than the payer is refunded to that Customer.\n"
    "                v_refund := app.post_credit_customer_refund(p_property_id, p_actor_id, p_draft_id);\n"
    "            ELSIF v_draft.payload->>'variant' = 'USD' THEN\n"
    "                -- A draft whose amount is no longer available is stale; it stays pending.\n"
)
CONFIRM_DECISION_BEFORE = (
    "            PERFORM app.confirm_financial_draft_record(\n"
    "                p_property_id, p_actor_id, p_draft_id, 'REFUND',\n"
    "                jsonb_build_object('refund_id', v_refund_id), 'financial.approve'\n"
    "            );\n"
)
CONFIRM_DECISION_AFTER = (
    CONFIRM_DECISION_BEFORE
    + "            -- The Credit Customer Refund's deferred check runs here, after its details row and the\n"
    "            -- decision (sub-slice 8f), so its refusal reaches the caller inside the command.\n"
    "            IF v_draft.payload->>'variant' = 'CREDIT_CUSTOMER' THEN\n"
    "                SET CONSTRAINTS ALL IMMEDIATE;\n"
    "            END IF;\n"
)
SOURCE_BEFORE = "            IF v_payment.status<>'RECEIVED' OR NEW.recipient_customer_id IS DISTINCT FROM v_payment.payer_customer_id\n"
SOURCE_AFTER = (
    "            -- BR-CREDIT-014 (V1-056 sub-slice 8f): a Credit that a credit Adjustment released to a\n"
    "            -- Customer other than the payer is paid to that Customer, only through its CREDIT_CUSTOMER\n"
    "            -- Refund draft; every other Refund is paid to the payer as before.\n"
    "            IF v_payment.status<>'RECEIVED'\n"
    "                OR (NEW.recipient_customer_id IS DISTINCT FROM v_payment.payer_customer_id\n"
    "                    AND NOT app.credit_customer_refund_allowed(NEW))\n"
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
            raise RuntimeError(f"Credit Customer Refund source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute("""
        -- The Credit a CREDIT_CUSTOMER Refund draft may pay: released by a credit Adjustment
        -- (BR-CREDIT-014) and owned by a Customer other than the payer of its source Payment. NULL
        -- for every other Credit.
        CREATE FUNCTION app.credit_customer_refund_basis(p_credit uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT jsonb_build_object('credit_id',credit.id,'customer_id',credit.customer_id,
                'payer_customer_id',payment.payer_customer_id,'payment_id',payment.id,
                'property_id',payment.property_id)
            FROM app.customer_credits credit
            JOIN app.payments payment ON payment.id=credit.source_payment_id
            WHERE credit.id=p_credit AND credit.customer_id<>payment.payer_customer_id
              AND EXISTS(SELECT 1 FROM app.invoice_credit_excess_releases release
                  WHERE release.customer_credit_id=credit.id)
        $$;

        -- The id of the Refund a CREDIT_CUSTOMER draft writes, so each draft pays at most once.
        CREATE FUNCTION app.credit_customer_refund_id(p_draft uuid)
        RETURNS uuid LANGUAGE sql IMMUTABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT md5('credit-customer-refund:' || p_draft::text)::uuid
        $$;

        -- The CREDIT_CUSTOMER draft a Refund row comes from: the same Property, Credit, recipient,
        -- amount and reason, and the Refund id derived from the draft. NULL when there is none.
        CREATE FUNCTION app.credit_customer_refund_draft(p_refund app.refunds)
        RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT draft.id FROM app.financial_drafts draft
            JOIN app.customer_credits credit ON credit.id=p_refund.source_customer_credit_id
            JOIN app.payments payment ON payment.id=credit.source_payment_id
            WHERE draft.kind='REFUND' AND draft.prepare_capability='refunds.create'
              AND draft.property_id=payment.property_id
              AND draft.payload->>'variant'='CREDIT_CUSTOMER'
              AND draft.payload->>'source_kind'='CREDIT'
              AND draft.payload->>'source_id'=credit.id::text
              AND draft.payload->>'recipient_customer_id'=p_refund.recipient_customer_id::text
              AND draft.payload->'amount_usd_cents'=to_jsonb(p_refund.usd_accounting_value_cents)
              AND draft.payload->>'reason'=p_refund.reason
              AND app.credit_customer_refund_id(draft.id)=p_refund.id
        $$;

        -- The Refund source check lifts the payer rule only for this case (BR-CREDIT-014): a Credit
        -- the variant covers, paid to its own Customer, with its CREDIT_CUSTOMER draft pending or
        -- confirmed by the Refund's approver.
        CREATE FUNCTION app.credit_customer_refund_allowed(p_refund app.refunds)
        RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_basis jsonb; v_draft uuid;
        BEGIN
            IF p_refund.source_customer_credit_id IS NULL THEN RETURN false; END IF;
            v_basis:=app.credit_customer_refund_basis(p_refund.source_customer_credit_id);
            IF v_basis IS NULL
                OR p_refund.recipient_customer_id IS DISTINCT FROM (v_basis->>'customer_id')::uuid
            THEN RETURN false; END IF;
            v_draft:=app.credit_customer_refund_draft(p_refund);
            IF v_draft IS NULL THEN RETURN false; END IF;
            RETURN NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                WHERE decision.draft_id=v_draft
                  AND (decision.decision<>'CONFIRMED' OR decision.decided_by<>p_refund.processed_by));
        END $$;

        -- Deferred: a Credit Refund paid to a Customer other than the payer commits only with its
        -- CREDIT_CUSTOMER draft CONFIRMED under financial.approve by the Refund's approver and its
        -- details row (BR-AUTH-010).
        CREATE FUNCTION app.assert_credit_customer_refund_confirmed()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_payer uuid; v_draft uuid;
        BEGIN
            IF NEW.source_customer_credit_id IS NULL THEN RETURN NULL; END IF;
            SELECT payment.payer_customer_id INTO STRICT v_payer FROM app.customer_credits credit
            JOIN app.payments payment ON payment.id=credit.source_payment_id
            WHERE credit.id=NEW.source_customer_credit_id;
            IF NEW.recipient_customer_id IS NOT DISTINCT FROM v_payer THEN RETURN NULL; END IF;
            v_draft:=app.credit_customer_refund_draft(NEW);
            IF v_draft IS NULL
                OR NOT EXISTS(SELECT 1 FROM app.refund_draft_details detail
                    WHERE detail.refund_id=NEW.id AND detail.draft_id=v_draft)
                OR NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                    WHERE decision.draft_id=v_draft AND decision.decision='CONFIRMED'
                      AND decision.authorization_reference='financial.approve'
                      AND decision.decided_by=NEW.processed_by)
            THEN RAISE EXCEPTION 'A Credit Refund to the Invoice Customer needs its draft confirmed under financial.approve by the same approver'
                USING ERRCODE='42501'; END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER refunds_credit_customer_confirmed AFTER INSERT ON app.refunds
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION app.assert_credit_customer_refund_confirmed();

        -- Record a Refund draft that pays a Credit to its own Customer (BR-CREDIT-014, BR-AUTH-010,
        -- BR-REFUND-014); it has no financial effect until a financial.approve holder confirms it.
        CREATE FUNCTION app.record_credit_customer_refund_draft(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid, p_credit_id uuid, p_amount bigint,
            p_reason text, p_refund_method_id uuid, p_reference_note text,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_customer uuid; v_payload jsonb; v_existing app.financial_drafts%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id, p_property_id);
            IF p_authorization_reference IS DISTINCT FROM 'refunds.create' THEN
                RAISE EXCEPTION 'Refund draft needs refunds.create' USING ERRCODE='42501';
            END IF;
            IF p_draft_id IS NULL OR p_draft_id='00000000-0000-0000-0000-000000000000'
                OR p_amount IS NULL OR p_amount NOT BETWEEN 1 AND 9000000000000000
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 1000
                OR p_reference_note IS NULL OR p_reference_note<>btrim(p_reference_note)
                OR length(p_reference_note) NOT BETWEEN 1 AND 500
                OR p_refund_method_id IS NULL
            THEN RAISE EXCEPTION 'Refund draft input is invalid' USING ERRCODE='P5202'; END IF;
            -- The Credit belongs to this Property (its Payment's Property), as for every Credit Refund.
            PERFORM app.require_usd_refund_source(p_property_id, 'CREDIT', p_credit_id);
            SELECT customer_id INTO STRICT v_customer FROM app.customer_credits WHERE id=p_credit_id;
            v_payload:=jsonb_build_object(
                'variant','CREDIT_CUSTOMER','source_kind','CREDIT','source_id',p_credit_id,
                'recipient_customer_id',v_customer,'amount_usd_cents',p_amount,'reason',p_reason,
                'refund_method_id',p_refund_method_id,'reference_note',p_reference_note
            );
            -- An exact repeat replays before any current-state check, as the other Refund drafts do.
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft_id::text, 0));
            SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft_id;
            IF FOUND THEN
                IF v_existing.property_id=p_property_id AND v_existing.kind='REFUND'
                    AND v_existing.prepared_by=p_actor_id AND v_existing.payload=v_payload
                THEN RETURN app.financial_draft_json(v_existing); END IF;
                RAISE EXCEPTION 'Refund draft identity was reused' USING ERRCODE='P5205';
            END IF;
            PERFORM 1 FROM app.refund_methods WHERE id=p_refund_method_id AND active;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='P5202';
            END IF;
            IF app.credit_customer_refund_basis(p_credit_id) IS NULL THEN
                RAISE EXCEPTION 'Only a Credit that a credit Adjustment released to a Customer other than the payer is refunded to that Customer'
                    USING ERRCODE='P5206';
            END IF;
            RETURN app.insert_financial_draft(
                p_property_id, p_actor_id, p_draft_id, 'REFUND', 'refunds.create', v_payload,
                NULL, p_reason
            );
        END $$;

        -- The only writer of a Credit Refund paid to a Customer other than the payer. Internal: only
        -- app.confirm_refund_draft calls it, under financial.approve, after its draft lock, method
        -- and key checks; it writes the Refund and the replay row, the caller the details row and
        -- the decision.
        CREATE FUNCTION app.post_credit_customer_refund(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog
            SET timezone='UTC' AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE; v_basis jsonb; v_credit uuid; v_amount bigint;
            v_id uuid; v_request jsonb; v_result jsonb;
        BEGIN
            SELECT * INTO STRICT v_draft FROM app.financial_drafts
            WHERE id=p_draft_id AND property_id=p_property_id AND kind='REFUND'
              AND payload->>'variant'='CREDIT_CUSTOMER';
            v_credit:=(v_draft.payload->>'source_id')::uuid;
            v_amount:=(v_draft.payload->>'amount_usd_cents')::bigint;
            v_id:=app.credit_customer_refund_id(p_draft_id);
            PERFORM app.require_usd_refund_source(p_property_id, 'CREDIT', v_credit);
            -- The lock order of every Credit Refund: the Payment, then the Credit.
            PERFORM app.lock_refund_payment_source(NULL, v_credit);
            v_basis:=app.credit_customer_refund_basis(v_credit);
            IF v_basis IS NULL
                OR (v_basis->>'customer_id')::uuid IS DISTINCT FROM (v_draft.payload->>'recipient_customer_id')::uuid
            THEN
                RAISE EXCEPTION 'Only a Credit that a credit Adjustment released to a Customer other than the payer is refunded to that Customer'
                    USING ERRCODE='P5206';
            END IF;
            -- A draft whose amount is no longer available is stale; it stays pending.
            IF v_amount>app.credit_available_value(v_credit) THEN
                RAISE EXCEPTION 'Refund draft amount is no longer available' USING ERRCODE='P5202';
            END IF;
            -- Its own deferred check stays deferred, so an earlier SET CONSTRAINTS ALL IMMEDIATE in
            -- the transaction does not refuse a valid confirmation (as the sub-slice 8d writer).
            SET CONSTRAINTS app.refunds_credit_customer_confirmed DEFERRED;
            INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_payment_id,
                source_customer_credit_id,usd_accounting_value_cents,refund_currency,refund_amount_minor,
                reason,processed_at,processed_by,authorization_reference)
            VALUES(v_id,'REF-'||v_id::text,(v_basis->>'customer_id')::uuid,NULL,v_credit,v_amount,'USD',
                v_amount,v_draft.payload->>'reason',clock_timestamp(),p_actor_id,'refunds.create');
            v_result:=app.refund_resource(p_property_id,v_id,p_actor_id,50,NULL,NULL);
            -- The approver's replay row, keyed by the draft id like every confirmed Refund draft.
            v_request:=jsonb_build_object('source_kind','CREDIT','source_id',v_credit,
                'recipient_customer_id',v_basis->'customer_id','amount_usd_cents',v_amount,
                'reason',v_draft.payload->>'reason');
            INSERT INTO app.refund_commands VALUES(p_property_id,p_actor_id,'CREATE_USD',p_draft_id,
                v_request,v_result,clock_timestamp());
            RETURN v_result;
        END $$;
    """)
    _patch(SOURCE, ((SOURCE_BEFORE, SOURCE_AFTER),))
    _patch(
        CONFIRM,
        (
            (CONFIRM_VARIANTS_BEFORE, CONFIRM_VARIANTS_AFTER),
            (CONFIRM_BRANCH_BEFORE, CONFIRM_BRANCH_AFTER),
            (CONFIRM_DECISION_BEFORE, CONFIRM_DECISION_AFTER),
        ),
    )
    for function in (RECORD, *INTERNAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Credit Customer Refund migration is forward-only")
