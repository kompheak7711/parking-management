# ruff: noqa: E501
"""Refund methods and Refund drafts (BR-REFUND-014, BR-AUTH-010, DL-069; V1-056 slice 3a).

Additive, except one owner-approved privilege change (answer to plan Q6, 2026-10-03): the
financial role loses direct EXECUTE on ``app.create_usd_refund`` and
``app.create_pet_usd_refund``. A Credit, Payment or Pet Deposit Refund is now recorded as a
draft by a ``refunds.create`` holder and takes effect only when a ``financial.approve`` holder
confirms it; the confirm function calls the existing create functions, so every earlier
Refund rule and check still applies. Every confirmed Refund records its method and reference
note. Refund methods are one configured list, seeded with Cash and Bank transfer. No earlier
Refund row is read or changed.
"""

from alembic import op

revision = "20261013_78"
down_revision = "20261012_77"
branch_labels = None
depends_on = None

RUNTIME = (
    "app.list_refund_methods(uuid,uuid)",
    "app.create_refund_method(uuid,uuid,uuid,text,text,text)",
    "app.set_refund_method_active(uuid,uuid,uuid,boolean,text)",
)
FINANCIAL = (
    "app.record_refund_draft(uuid,uuid,uuid,text,text,uuid,uuid,bigint,text,uuid,text,text)",
    "app.confirm_refund_draft(uuid,uuid,uuid,text)",
)
INTERNAL = (
    "app.refund_method_json(app.refund_methods)",
    "app.reject_refund_method_mutation()",
    "app.reject_refund_draft_detail_mutation()",
)
RETIRED = (
    "app.create_usd_refund(uuid,uuid,uuid,text,uuid,bigint,text)",
    "app.create_pet_usd_refund(uuid,uuid,uuid,uuid,uuid,bigint,text)",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.refund_methods (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            code text NOT NULL UNIQUE CHECK (code ~ '^[A-Z][A-Z0-9_]{1,39}$'),
            display_name text NOT NULL
                CHECK (display_name = btrim(display_name) AND length(display_name) BETWEEN 1 AND 120),
            active boolean NOT NULL,
            seeded boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            CONSTRAINT refund_method_author CHECK (seeded OR created_by IS NOT NULL)
        );

        CREATE FUNCTION app.reject_refund_method_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP <> 'UPDATE'
                OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.code IS DISTINCT FROM OLD.code
                OR NEW.display_name IS DISTINCT FROM OLD.display_name
                OR NEW.seeded IS DISTINCT FROM OLD.seeded
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.updated_by IS NULL
                OR NEW.updated_at < OLD.updated_at
            THEN
                RAISE EXCEPTION 'Refund Method identity and history are protected'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER refund_methods_protected BEFORE UPDATE OR DELETE
            ON app.refund_methods FOR EACH ROW
            EXECUTE FUNCTION app.reject_refund_method_mutation();
        CREATE TRIGGER refund_methods_no_truncate BEFORE TRUNCATE
            ON app.refund_methods FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_refund_method_mutation();

        INSERT INTO app.refund_methods(id, code, display_name, active, seeded)
        VALUES
            (gen_random_uuid(), 'CASH', 'Cash', true, true),
            (gen_random_uuid(), 'BANK_TRANSFER', 'Bank transfer (ABA or another bank)', true, true);

        CREATE TABLE app.refund_draft_details (
            refund_id uuid PRIMARY KEY REFERENCES app.refunds(id) ON DELETE RESTRICT,
            draft_id uuid NOT NULL UNIQUE REFERENCES app.financial_drafts(id) ON DELETE RESTRICT,
            refund_method_id uuid NOT NULL REFERENCES app.refund_methods(id) ON DELETE RESTRICT,
            reference_note text NOT NULL
                CHECK (reference_note = btrim(reference_note) AND length(reference_note) BETWEEN 1 AND 500),
            recorded_at timestamptz NOT NULL
        );
        CREATE FUNCTION app.reject_refund_draft_detail_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Refund method history is append-only' USING ERRCODE = '55000';
        END $$;
        CREATE TRIGGER refund_draft_details_immutable BEFORE UPDATE OR DELETE
            ON app.refund_draft_details FOR EACH ROW
            EXECUTE FUNCTION app.reject_refund_draft_detail_mutation();
        CREATE TRIGGER refund_draft_details_no_truncate BEFORE TRUNCATE
            ON app.refund_draft_details FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_refund_draft_detail_mutation();

        CREATE FUNCTION app.refund_method_json(p_method app.refund_methods)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT jsonb_build_object(
                'id', p_method.id, 'code', p_method.code, 'display_name', p_method.display_name,
                'active', p_method.active, 'seeded', p_method.seeded,
                'updated_at', p_method.updated_at
            )
        $$;

        CREATE FUNCTION app.list_refund_methods(p_property_id uuid, p_actor_id uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            RETURN jsonb_build_object('items', COALESCE((
                SELECT jsonb_agg(app.refund_method_json(method) ORDER BY method.code)
                FROM app.refund_methods AS method
            ), '[]'::jsonb));
        END $$;

        CREATE FUNCTION app.create_refund_method(
            p_property_id uuid, p_actor_id uuid, p_method_id uuid, p_code text,
            p_display_name text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_method app.refund_methods%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            IF p_authorization_reference IS DISTINCT FROM 'property.manage' THEN
                RAISE EXCEPTION 'Refund Method change needs property.manage' USING ERRCODE = '42501';
            END IF;
            IF p_method_id IS NULL OR p_code IS NULL OR p_display_name IS NULL THEN
                RAISE EXCEPTION 'Refund Method input is invalid' USING ERRCODE = '22023';
            END IF;
            SELECT * INTO v_method FROM app.refund_methods WHERE id = p_method_id;
            IF FOUND THEN
                IF v_method.code = p_code AND v_method.display_name = p_display_name
                    AND v_method.created_by = p_actor_id
                THEN RETURN app.refund_method_json(v_method); END IF;
                RAISE EXCEPTION 'Refund Method identity was reused' USING ERRCODE = '23505';
            END IF;
            INSERT INTO app.refund_methods(
                id, code, display_name, active, seeded, created_by, updated_by
            ) VALUES (
                p_method_id, p_code, p_display_name, true, false, p_actor_id, p_actor_id
            ) RETURNING * INTO v_method;
            RETURN app.refund_method_json(v_method);
        END $$;

        CREATE FUNCTION app.set_refund_method_active(
            p_property_id uuid, p_actor_id uuid, p_method_id uuid, p_active boolean,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_method app.refund_methods%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            IF p_authorization_reference IS DISTINCT FROM 'property.manage' THEN
                RAISE EXCEPTION 'Refund Method change needs property.manage' USING ERRCODE = '42501';
            END IF;
            IF p_active IS NULL THEN
                RAISE EXCEPTION 'Refund Method input is invalid' USING ERRCODE = '22023';
            END IF;
            SELECT * INTO v_method FROM app.refund_methods WHERE id = p_method_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Refund Method was not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_method.active = p_active THEN RETURN app.refund_method_json(v_method); END IF;
            UPDATE app.refund_methods
            SET active = p_active, updated_at = clock_timestamp(), updated_by = p_actor_id
            WHERE id = p_method_id RETURNING * INTO v_method;
            RETURN app.refund_method_json(v_method);
        END $$;

        CREATE FUNCTION app.record_refund_draft(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid, p_variant text,
            p_source_kind text, p_source_id uuid, p_review_id uuid, p_amount bigint,
            p_reason text, p_refund_method_id uuid, p_reference_note text,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_payload jsonb; v_existing app.financial_drafts%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id, p_property_id);
            IF p_authorization_reference IS DISTINCT FROM 'refunds.create' THEN
                RAISE EXCEPTION 'Refund draft needs refunds.create' USING ERRCODE = '42501';
            END IF;
            IF p_draft_id IS NULL OR p_draft_id = '00000000-0000-0000-0000-000000000000'
                OR p_amount IS NULL OR p_amount NOT BETWEEN 1 AND 9000000000000000
                OR p_reason IS NULL OR p_reason <> btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 1000
                OR p_reference_note IS NULL OR p_reference_note <> btrim(p_reference_note)
                OR length(p_reference_note) NOT BETWEEN 1 AND 500
                OR p_refund_method_id IS NULL
            THEN RAISE EXCEPTION 'Refund draft input is invalid' USING ERRCODE = 'P5202'; END IF;
            IF p_variant = 'USD' AND p_review_id IS NULL AND p_source_id IS NOT NULL
                AND p_source_kind IN ('PAYMENT','CREDIT')
            THEN
                v_payload := jsonb_build_object(
                    'variant', 'USD', 'source_kind', p_source_kind, 'source_id', p_source_id,
                    'amount_usd_cents', p_amount, 'reason', p_reason,
                    'refund_method_id', p_refund_method_id, 'reference_note', p_reference_note
                );
            ELSIF p_variant = 'PET' AND p_source_kind IS NULL AND p_review_id IS NOT NULL
                AND p_source_id IS NOT NULL
            THEN
                v_payload := jsonb_build_object(
                    'variant', 'PET', 'deposit_id', p_source_id, 'pet_refund_review_id', p_review_id,
                    'amount_usd_cents', p_amount, 'reason', p_reason,
                    'refund_method_id', p_refund_method_id, 'reference_note', p_reference_note
                );
            ELSE
                RAISE EXCEPTION 'Refund draft source is invalid' USING ERRCODE = 'P5202';
            END IF;
            -- An exact repeat replays before any current-state check, as the create functions did.
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
            IF p_variant = 'USD' THEN
                PERFORM app.require_usd_refund_source(p_property_id, p_source_kind, p_source_id);
            ELSIF app.pet_refund_qualification(p_property_id, p_source_id, p_review_id) IS NULL THEN
                RAISE EXCEPTION 'Qualified Pet Refund source not found' USING ERRCODE = 'P5201';
            END IF;
            RETURN app.insert_financial_draft(
                p_property_id, p_actor_id, p_draft_id, 'REFUND', 'refunds.create', v_payload,
                NULL, p_reason
            );
        END $$;

        CREATE FUNCTION app.confirm_refund_draft(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
            SET timezone = 'UTC' AS $$
        DECLARE
            v_draft app.financial_drafts%ROWTYPE;
            v_refund jsonb;
            v_refund_id uuid;
            v_available bigint;
            v_qualification jsonb;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            PERFORM app.assert_active_financial_actor(p_actor_id, p_property_id);
            IF p_authorization_reference IS DISTINCT FROM 'financial.approve' THEN
                RAISE EXCEPTION 'Only financial.approve may confirm a Refund' USING ERRCODE = '42501';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft_id::text, 0));
            SELECT detail.refund_id INTO v_refund_id
            FROM app.refund_draft_details AS detail
            JOIN app.financial_drafts AS draft ON draft.id = detail.draft_id
            JOIN app.financial_draft_decisions AS decision ON decision.draft_id = detail.draft_id
            WHERE detail.draft_id = p_draft_id AND draft.property_id = p_property_id
              AND decision.decided_by = p_actor_id;
            IF FOUND THEN
                -- An exact replay returns the original Refund response, as before drafts.
                SELECT * INTO STRICT v_draft FROM app.financial_drafts WHERE id = p_draft_id;
                SELECT command.response INTO STRICT v_refund FROM app.refund_commands AS command
                WHERE command.property_id = p_property_id AND command.actor_id = p_actor_id
                  AND command.action IN ('CREATE_USD','CREATE_PET_USD')
                  AND command.idempotency_key = p_draft_id;
                RETURN jsonb_build_object('draft', app.financial_draft_json(v_draft), 'refund', v_refund);
            END IF;
            v_draft := app.lock_pending_financial_draft(p_property_id, p_draft_id);
            IF v_draft.kind <> 'REFUND' OR v_draft.prepare_capability <> 'refunds.create'
                OR v_draft.payload->>'variant' IS NULL
                OR v_draft.payload->>'variant' NOT IN ('USD','PET')
            THEN
                RAISE EXCEPTION 'Financial draft is not a Credit, Payment or Pet Refund'
                    USING ERRCODE = 'P5202';
            END IF;
            PERFORM 1 FROM app.refund_methods
            WHERE id = (v_draft.payload->>'refund_method_id')::uuid AND active FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE = 'P5202';
            END IF;
            -- The draft id must not already be another Refund command key of this approver.
            IF EXISTS (
                SELECT 1 FROM app.refund_commands AS command
                WHERE command.property_id = p_property_id AND command.actor_id = p_actor_id
                  AND command.idempotency_key = p_draft_id
            ) THEN
                RAISE EXCEPTION 'Refund draft identity was reused' USING ERRCODE = 'P5205';
            END IF;
            IF v_draft.payload->>'variant' = 'USD' THEN
                -- A draft whose amount is no longer available is stale; it stays pending.
                v_available := CASE
                    WHEN v_draft.payload->>'source_kind' = 'PAYMENT'
                        THEN app.payment_available_value((v_draft.payload->>'source_id')::uuid)
                    ELSE app.credit_available_value((v_draft.payload->>'source_id')::uuid)
                END;
                IF (v_draft.payload->>'amount_usd_cents')::bigint > v_available THEN
                    RAISE EXCEPTION 'Refund draft amount is no longer available'
                        USING ERRCODE = 'P5202';
                END IF;
                -- New unpaid charges of the payer also make a Payment draft stale.
                IF v_draft.payload->>'source_kind' = 'PAYMENT' THEN
                    BEGIN
                        PERFORM app.assert_payment_excess_eligible(
                            (v_draft.payload->>'source_id')::uuid
                        );
                    EXCEPTION WHEN check_violation THEN
                        RAISE EXCEPTION 'Refund draft is stale: the payer has unpaid obligations'
                            USING ERRCODE = 'P5202';
                    END;
                END IF;
                v_refund := app.create_usd_refund(
                    p_property_id, p_actor_id, p_draft_id, v_draft.payload->>'source_kind',
                    (v_draft.payload->>'source_id')::uuid,
                    (v_draft.payload->>'amount_usd_cents')::bigint, v_draft.payload->>'reason'
                );
            ELSE
                v_qualification := app.pet_refund_qualification(
                    p_property_id, (v_draft.payload->>'deposit_id')::uuid,
                    (v_draft.payload->>'pet_refund_review_id')::uuid
                );
                IF v_qualification IS NULL THEN
                    RAISE EXCEPTION 'Refund draft is stale: the Pet Refund source is no longer qualified'
                        USING ERRCODE = 'P5202';
                END IF;
                IF (v_draft.payload->>'amount_usd_cents')::bigint
                    > (v_qualification->>'available_usd_cents')::bigint
                THEN
                    RAISE EXCEPTION 'Refund draft amount is no longer available'
                        USING ERRCODE = 'P5202';
                END IF;
                v_refund := app.create_pet_usd_refund(
                    p_property_id, p_actor_id, p_draft_id, (v_draft.payload->>'deposit_id')::uuid,
                    (v_draft.payload->>'pet_refund_review_id')::uuid,
                    (v_draft.payload->>'amount_usd_cents')::bigint, v_draft.payload->>'reason'
                );
            END IF;
            v_refund_id := (v_refund->'refund'->>'id')::uuid;
            INSERT INTO app.refund_draft_details(
                refund_id, draft_id, refund_method_id, reference_note, recorded_at
            ) VALUES (
                v_refund_id, p_draft_id, (v_draft.payload->>'refund_method_id')::uuid,
                v_draft.payload->>'reference_note', clock_timestamp()
            );
            PERFORM app.confirm_financial_draft_record(
                p_property_id, p_actor_id, p_draft_id, 'REFUND',
                jsonb_build_object('refund_id', v_refund_id), 'financial.approve'
            );
            RETURN jsonb_build_object('draft', app.financial_draft_json(v_draft), 'refund', v_refund);
        END $$;

        REVOKE ALL ON TABLE app.refund_methods, app.refund_draft_details
            FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap;
        """
    )
    for function in (*RUNTIME, *FINANCIAL, *INTERNAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in RUNTIME:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")
    for function in FINANCIAL:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")
    for function in RETIRED:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {function} FROM prm_financial")


def downgrade() -> None:
    raise RuntimeError("Refund methods and Refund drafts are forward-only")
