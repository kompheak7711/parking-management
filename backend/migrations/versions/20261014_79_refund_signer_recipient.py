# ruff: noqa: E501
"""Deposit Refund to another Lease Signer with a written agreement (BR-REFUND-015; V1-056 slice 3a-2).

Owner answers of 2026-10-04 (Q-2026-10-04-4): a Pet Deposit Refund goes to the Primary Tenant
unless all Lease Signers agreed in writing that another Signer receives it. The agreement is
free text recorded with the Refund draft. The Refund row names the Signer who was paid; the
Customer Ledger books every Deposit Refund on the Deposit owner's ledger (a new projection
version) and names the Signer who was paid; the receiving Signer's ledger shows no balance
change.

Relaxing and additive: the Pet Refund source check also accepts a Signer named by a recorded
agreement; a new Refund draft overload takes the Signer and the agreement; the confirm function
gains the agreement path; the ledger view is rebuilt with the Deposit owner as the ledger
Customer for Deposit Refunds. Every earlier Deposit Refund was paid to the Deposit owner, so
every earlier projection result stays the same; the upgrade refuses to run if any earlier
Deposit Refund was paid to someone else. No earlier row is changed.
"""

import importlib.util
from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "20261014_79"
down_revision = "20261013_78"
branch_labels = None
depends_on = None

NEW_RECORD = "app.record_refund_draft(uuid,uuid,uuid,text,text,uuid,uuid,bigint,text,uuid,text,text,uuid,text)"
CONFIRM = "app.confirm_refund_draft(uuid,uuid,uuid,text)"
ASSERT_PET = "app.assert_pet_refund_source(app.refunds)"
INTERNAL = (
    "app.refund_recipient_agreed(uuid,uuid,uuid,uuid)",
    "app.create_pet_usd_refund_to_signer(uuid,uuid,uuid,uuid,uuid,bigint,text,uuid,uuid)",
    "app.reject_refund_recipient_agreement_mutation()",
)

ASSERT_ANCHOR = "IF p_refund.recipient_customer_id IS DISTINCT FROM (v_source->>'recipient_customer_id')::uuid\n"
ASSERT_REPLACEMENT = (
    "IF (p_refund.recipient_customer_id IS DISTINCT FROM (v_source->>'recipient_customer_id')::uuid\n"
    "                    AND NOT app.refund_recipient_agreed(\n"
    "                        p_refund.id, p_refund.recipient_customer_id, (v_source->>'lease_id')::uuid,\n"
    "                        p_refund.source_deposit_id\n"
    "                    ))\n"
)
CONFIRM_ANCHOR = """                v_refund := app.create_pet_usd_refund(
                    p_property_id, p_actor_id, p_draft_id, (v_draft.payload->>'deposit_id')::uuid,
                    (v_draft.payload->>'pet_refund_review_id')::uuid,
                    (v_draft.payload->>'amount_usd_cents')::bigint, v_draft.payload->>'reason'
                );
"""
CONFIRM_REPLACEMENT = """                IF v_draft.payload ? 'recipient_customer_id' THEN
                    -- BR-REFUND-015: the agreement is written first; the Refund names the Signer.
                    v_refund_id := gen_random_uuid();
                    INSERT INTO app.refund_recipient_agreements(
                        refund_id, draft_id, deposit_id, lease_id, recipient_customer_id,
                        agreement_text, recorded_at
                    ) VALUES (
                        v_refund_id, p_draft_id, (v_draft.payload->>'deposit_id')::uuid,
                        (v_qualification->>'lease_id')::uuid,
                        (v_draft.payload->>'recipient_customer_id')::uuid,
                        v_draft.payload->>'signer_agreement', clock_timestamp()
                    );
                    v_refund := app.create_pet_usd_refund_to_signer(
                        p_property_id, p_actor_id, p_draft_id, (v_draft.payload->>'deposit_id')::uuid,
                        (v_draft.payload->>'pet_refund_review_id')::uuid,
                        (v_draft.payload->>'amount_usd_cents')::bigint, v_draft.payload->>'reason',
                        v_refund_id, (v_draft.payload->>'recipient_customer_id')::uuid
                    );
                ELSE
                v_refund := app.create_pet_usd_refund(
                    p_property_id, p_actor_id, p_draft_id, (v_draft.payload->>'deposit_id')::uuid,
                    (v_draft.payload->>'pet_refund_review_id')::uuid,
                    (v_draft.payload->>'amount_usd_cents')::bigint, v_draft.payload->>'reason'
                );
                END IF;
"""


def _definition(signature: str) -> str:
    return str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _replace_once(definition: str, anchor: str, replacement: str, name: str) -> str:
    if definition.count(anchor) != 1:
        raise RuntimeError(f"Refund recipient source contract changed: {name}")
    return definition.replace(anchor, replacement, 1)


def _ledger_projection() -> str:
    """Rebuild the ledger effects view from the revision 48 builders, Deposit Refunds on the owner."""
    path = Path(__file__).with_name("20260909_48_customer_ledger_projection.py")
    spec = importlib.util.spec_from_file_location("customer_ledger_projection_48", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Customer ledger projection source is missing")
    ledger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ledger)
    refunds = ledger.refund_components()
    owner = "CASE WHEN d.id IS NOT NULL THEN d.customer_id ELSE f.recipient_customer_id END"
    paid_to = (
        "|| CASE WHEN d.id IS NOT NULL AND f.recipient_customer_id IS DISTINCT FROM d.customer_id "
        "THEN jsonb_build_object('paid_to_customer_id',f.recipient_customer_id) ELSE '{}'::jsonb END"
    )
    rebuilt = []
    for component in refunds:
        customer = "f.recipient_customer_id::uuid AS customer_id"
        audit_end = " AS source_audit\n"
        if component.count(customer) != 1 or component.count(audit_end) != 1:
            raise RuntimeError("Customer ledger Refund component contract changed")
        component = component.replace(customer, f"({owner})::uuid AS customer_id")
        component = component.replace(audit_end, f" {paid_to} AS source_audit\n")
        rebuilt.append(component)
    rows = ledger.invoice_components() + ledger.charge_components() + ledger.payment_components()
    rows += ledger.application_components(credit=False) + ledger.credit_components()
    rows += ledger.application_components(credit=True) + ledger.deposit_components() + rebuilt
    return (
        "CREATE OR REPLACE VIEW app.customer_ledger_effects WITH(security_invoker=true) AS "
        + " UNION ALL ".join(rows)
    )


def upgrade() -> None:
    # The owner-ledger booking keeps earlier results only if every earlier Deposit Refund was
    # paid to the Deposit owner; refuse to upgrade otherwise.
    mismatched = (
        op.get_bind()
        .execute(
            text(
                "SELECT count(*) FROM app.refunds f JOIN app.deposits d ON d.id=f.source_deposit_id "
                "WHERE f.recipient_customer_id IS DISTINCT FROM d.customer_id"
            )
        )
        .scalar_one()
    )
    if mismatched:
        raise RuntimeError("An earlier Deposit Refund was not paid to the Deposit owner")
    op.execute(
        """
        CREATE TABLE app.refund_recipient_agreements (
            refund_id uuid PRIMARY KEY REFERENCES app.refunds(id) ON DELETE RESTRICT
                DEFERRABLE INITIALLY DEFERRED,
            draft_id uuid NOT NULL UNIQUE REFERENCES app.financial_drafts(id) ON DELETE RESTRICT,
            deposit_id uuid NOT NULL REFERENCES app.deposits(id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            recipient_customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            agreement_text text NOT NULL
                CHECK (agreement_text = btrim(agreement_text) AND length(agreement_text) BETWEEN 1 AND 2000),
            recorded_at timestamptz NOT NULL
        );
        CREATE FUNCTION app.reject_refund_recipient_agreement_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Refund recipient agreements are append-only' USING ERRCODE = '55000';
        END $$;
        CREATE TRIGGER refund_recipient_agreements_immutable BEFORE UPDATE OR DELETE
            ON app.refund_recipient_agreements FOR EACH ROW
            EXECUTE FUNCTION app.reject_refund_recipient_agreement_mutation();
        CREATE TRIGGER refund_recipient_agreements_no_truncate BEFORE TRUNCATE
            ON app.refund_recipient_agreements FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_refund_recipient_agreement_mutation();

        CREATE FUNCTION app.refund_recipient_agreed(
            p_refund_id uuid, p_recipient_customer_id uuid, p_lease_id uuid, p_deposit_id uuid
        ) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.refund_recipient_agreements AS agreement
                JOIN app.lease_signers AS signer
                    ON signer.lease_id = agreement.lease_id
                   AND signer.customer_id = agreement.recipient_customer_id
                   AND signer.signed_at IS NOT NULL
                WHERE agreement.refund_id = p_refund_id
                  AND agreement.recipient_customer_id = p_recipient_customer_id
                  AND agreement.lease_id = p_lease_id
                  AND agreement.deposit_id = p_deposit_id
            )
        $$;

        CREATE FUNCTION app.create_pet_usd_refund_to_signer(
            p_property_id uuid, p_actor_id uuid, p_key uuid, p_deposit_id uuid, p_review_id uuid,
            p_amount bigint, p_reason text, p_refund_id uuid, p_recipient_customer_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
            SET timezone = 'UTC' AS $$
        DECLARE v_request jsonb; v_result jsonb;
        BEGIN
            v_request := jsonb_build_object(
                'deposit_id', p_deposit_id, 'pet_refund_review_id', p_review_id,
                'amount_usd_cents', p_amount, 'reason', p_reason,
                'recipient_customer_id', p_recipient_customer_id
            );
            v_result := app.refund_command_replay(
                p_property_id, p_actor_id, 'CREATE_PET_USD', p_key, v_request
            );
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_deposit_id IS NULL OR p_review_id IS NULL OR p_refund_id IS NULL
                OR p_deposit_id = '00000000-0000-0000-0000-000000000000'
                OR p_review_id = '00000000-0000-0000-0000-000000000000'
                OR p_recipient_customer_id IS NULL
                OR p_amount IS NULL OR p_amount NOT BETWEEN 1 AND 9000000000000000
                OR p_reason IS NULL OR p_reason <> btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 1000
            THEN RAISE EXCEPTION 'Pet Refund input is invalid' USING ERRCODE = 'P5202'; END IF;
            PERFORM app.lock_pet_refund_source(p_property_id, p_deposit_id, p_review_id);
            INSERT INTO app.refunds(
                id, refund_number, recipient_customer_id, source_deposit_id, pet_refund_review_id,
                usd_accounting_value_cents, refund_currency, refund_amount_minor, reason,
                processed_at, processed_by, authorization_reference
            ) VALUES (
                p_refund_id, 'REF-' || p_refund_id::text, p_recipient_customer_id, p_deposit_id,
                p_review_id, p_amount, 'USD', p_amount, p_reason, clock_timestamp(), p_actor_id,
                'refunds.create'
            );
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result := app.refund_resource(p_property_id, p_refund_id, p_actor_id, 50, NULL, NULL);
            INSERT INTO app.refund_commands VALUES (
                p_property_id, p_actor_id, 'CREATE_PET_USD', p_key, v_request, v_result, clock_timestamp()
            );
            RETURN v_result;
        END $$;

        CREATE FUNCTION app.record_refund_draft(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid, p_variant text,
            p_source_kind text, p_source_id uuid, p_review_id uuid, p_amount bigint,
            p_reason text, p_refund_method_id uuid, p_reference_note text,
            p_authorization_reference text, p_recipient_customer_id uuid, p_signer_agreement text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_payload jsonb;
            v_existing app.financial_drafts%ROWTYPE;
            v_qualification jsonb;
        BEGIN
            IF p_recipient_customer_id IS NULL AND p_signer_agreement IS NULL THEN
                RETURN app.record_refund_draft(
                    p_property_id, p_actor_id, p_draft_id, p_variant, p_source_kind, p_source_id,
                    p_review_id, p_amount, p_reason, p_refund_method_id, p_reference_note,
                    p_authorization_reference
                );
            END IF;
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id, p_property_id);
            IF p_authorization_reference IS DISTINCT FROM 'refunds.create' THEN
                RAISE EXCEPTION 'Refund draft needs refunds.create' USING ERRCODE = '42501';
            END IF;
            -- BR-REFUND-015: another Signer only for a Deposit Refund, with the written agreement.
            IF p_variant IS DISTINCT FROM 'PET' OR p_source_kind IS NOT NULL
                OR p_source_id IS NULL OR p_review_id IS NULL
                OR p_source_id = '00000000-0000-0000-0000-000000000000'
                OR p_review_id = '00000000-0000-0000-0000-000000000000'
                OR p_recipient_customer_id IS NULL
                OR p_signer_agreement IS NULL OR p_signer_agreement <> btrim(p_signer_agreement)
                OR length(p_signer_agreement) NOT BETWEEN 1 AND 2000
                OR p_draft_id IS NULL OR p_draft_id = '00000000-0000-0000-0000-000000000000'
                OR p_amount IS NULL OR p_amount NOT BETWEEN 1 AND 9000000000000000
                OR p_reason IS NULL OR p_reason <> btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 1000
                OR p_reference_note IS NULL OR p_reference_note <> btrim(p_reference_note)
                OR length(p_reference_note) NOT BETWEEN 1 AND 500
                OR p_refund_method_id IS NULL
            THEN RAISE EXCEPTION 'Refund draft input is invalid' USING ERRCODE = 'P5202'; END IF;
            v_payload := jsonb_build_object(
                'variant', 'PET', 'deposit_id', p_source_id, 'pet_refund_review_id', p_review_id,
                'amount_usd_cents', p_amount, 'reason', p_reason,
                'refund_method_id', p_refund_method_id, 'reference_note', p_reference_note,
                'recipient_customer_id', p_recipient_customer_id,
                'signer_agreement', p_signer_agreement
            );
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft_id::text, 0));
            SELECT * INTO v_existing FROM app.financial_drafts WHERE id = p_draft_id;
            IF FOUND THEN
                IF v_existing.property_id = p_property_id AND v_existing.kind = 'REFUND'
                    AND v_existing.prepared_by = p_actor_id AND v_existing.payload = v_payload
                THEN RETURN app.financial_draft_json(v_existing); END IF;
                RAISE EXCEPTION 'Refund draft identity was reused' USING ERRCODE = 'P5205';
            END IF;
            PERFORM 1 FROM app.refund_methods WHERE id = p_refund_method_id AND active;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE = 'P5202';
            END IF;
            v_qualification := app.pet_refund_qualification(p_property_id, p_source_id, p_review_id);
            IF v_qualification IS NULL THEN
                RAISE EXCEPTION 'Qualified Pet Refund source not found' USING ERRCODE = 'P5201';
            END IF;
            IF p_recipient_customer_id = (v_qualification->>'recipient_customer_id')::uuid THEN
                RAISE EXCEPTION 'The Primary Tenant needs no Signer agreement' USING ERRCODE = 'P5202';
            END IF;
            PERFORM 1 FROM app.lease_signers
            WHERE lease_id = (v_qualification->>'lease_id')::uuid
              AND customer_id = p_recipient_customer_id AND signed_at IS NOT NULL;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'The Refund recipient must be a Signer of the Lease'
                    USING ERRCODE = 'P5202';
            END IF;
            RETURN app.insert_financial_draft(
                p_property_id, p_actor_id, p_draft_id, 'REFUND', 'refunds.create', v_payload,
                NULL, p_reason
            );
        END $$;

        REVOKE ALL ON TABLE app.refund_recipient_agreements
            FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap;
        """
    )
    op.execute(
        _replace_once(_definition(ASSERT_PET), ASSERT_ANCHOR, ASSERT_REPLACEMENT, ASSERT_PET)
    )
    confirm = _definition(CONFIRM)
    confirm = _replace_once(confirm, CONFIRM_ANCHOR, CONFIRM_REPLACEMENT, CONFIRM)
    op.execute(confirm)
    op.execute(_ledger_projection())
    for function in (*INTERNAL, NEW_RECORD):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {NEW_RECORD} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Refund recipient agreements are forward-only")
