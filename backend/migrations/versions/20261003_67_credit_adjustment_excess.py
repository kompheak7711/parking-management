# ruff: noqa: E501
"""Record credit Adjustment excess as Customer Credit through append-only reversals (BR-INV-044)."""

from alembic import op
from sqlalchemy import text

revision = "20261003_67"
down_revision = "20261003_66"
branch_labels = None
depends_on = None

REASON = "Invoice adjustment credit excess"

ADJUST = "app.adjust_invoice(uuid,uuid,uuid,uuid,uuid,text,integer,text,bigint,text,text,uuid,uuid)"

ADJUST_REPLACEMENTS = (
    (
        "DECLARE v_min_resulting numeric; v_resulting numeric;",
        "DECLARE v_min_resulting numeric; v_resulting numeric;\n"
        "        DECLARE v_excess bigint; v_plan jsonb; v_effect jsonb;",
    ),
    (
        "SELECT min(resulting-app.invoice_line_application_value_at(id,'infinity')),sum(resulting)",
        "SELECT min(CASE WHEN id=p_line_id AND p_adjustment_type='CREDIT' THEN resulting\n"
        "                ELSE resulting-app.invoice_line_application_value_at(id,'infinity') END),sum(resulting)",
    ),
    (
        "            v_before:=app.invoice_resource_snapshot(p_invoice_id);\n"
        "            v_now:=clock_timestamp(); v_business_date:=timezone(v_timezone,v_now)::date;\n",
        """            v_before:=app.invoice_resource_snapshot(p_invoice_id);
            IF p_adjustment_type='CREDIT' THEN
                v_excess:=app.invoice_line_application_value_at(p_line_id,'infinity')
                    -(app.invoice_adjusted_line_obligation(p_line_id)-p_amount);
                IF v_excess>0 THEN
                    v_plan:=app.reverse_line_value_for_credit_excess(
                        p_invoice_id,p_line_id,v_excess,p_actor_id);
                END IF;
            END IF;
            v_now:=CASE WHEN v_plan IS NULL THEN clock_timestamp()
                ELSE app.credit_excess_instant(p_invoice_id,NULL) END;
            v_business_date:=timezone(v_timezone,v_now)::date;
""",
    ),
    (
        "p_source_reference,p_reason,v_now,p_actor_id,'invoices.adjust');\n",
        """p_source_reference,p_reason,v_now,p_actor_id,'invoices.adjust');
            IF v_plan IS NOT NULL THEN
                v_effect:=app.repost_line_value_after_credit_excess(
                    p_invoice_id,p_line_id,v_plan,p_actor_id,p_adjustment_id);
            END IF;
""",
    ),
    (
        "version=version+1,updated_at=v_now,updated_by=p_actor_id WHERE id=p_invoice_id;",
        "version=version+1,updated_at=CASE WHEN v_plan IS NULL THEN v_now\n"
        "                    ELSE GREATEST(v_now,updated_at) END,updated_by=p_actor_id WHERE id=p_invoice_id;",
    ),
    (
        "            v_result:=app.invoice_resource_snapshot(p_invoice_id);\n",
        """            v_result:=app.invoice_resource_snapshot(p_invoice_id);
            IF v_effect IS NOT NULL THEN
                v_result:=v_result||jsonb_build_object('adjustment_effect',v_effect);
            END IF;
""",
    ),
)

ALLOCATION_AUDIT = (
    (
        "v_reason:='Explicitly confirmed allocation';",
        "v_reason:=CASE WHEN EXISTS(SELECT 1 FROM app.invoice_credit_excess_releases release\n"
        "                    WHERE release.replacement_payment_allocation_id=NEW.id)\n"
        f"                    THEN '{REASON}' ELSE 'Explicitly confirmed allocation' END;",
    ),
)

APPLICATION_AUDIT = (
    (
        "v_reason:='Confirmed Credit application';",
        "v_reason:=CASE WHEN EXISTS(SELECT 1 FROM app.invoice_credit_excess_releases release\n"
        "                    WHERE release.replacement_credit_application_id=NEW.id)\n"
        f"                    THEN '{REASON}' ELSE 'Confirmed Credit application' END;",
    ),
)

APPLICATION_SOURCE = (
    (
        "                IF NEW.proposal_trace IS NOT NULL AND (\n",
        "                IF NEW.proposal_trace IS NOT NULL AND NOT EXISTS(\n"
        "                    SELECT 1 FROM app.invoice_credit_excess_releases release\n"
        "                    WHERE release.replacement_credit_application_id=NEW.id) AND (\n",
    ),
)

CREDIT_RECOGNITION = (
    (
        "            PERFORM app.assert_payment_excess_eligible(v_payment.id);\n"
        "            IF v_payment.status<>'RECEIVED' OR NEW.customer_id IS DISTINCT FROM v_payment.payer_customer_id\n",
        """            -- Adjustment excess (DL-064 option a) belongs to the Invoice Customer at once.
            SELECT invoice.customer_id INTO v_adjustment_customer
            FROM app.invoice_credit_excess_releases release
            JOIN app.invoice_adjustments adjustment ON adjustment.id=release.invoice_adjustment_id
            JOIN app.invoices invoice ON invoice.id=adjustment.invoice_id
            WHERE release.customer_credit_id=NEW.id AND adjustment.adjustment_type='CREDIT'
              AND release.released_usd_cents=NEW.recognized_usd_cents
              AND release.source_kind='PAYMENT_ALLOCATION';
            IF v_adjustment_customer IS NULL THEN
                PERFORM app.assert_payment_excess_eligible(v_payment.id);
            END IF;
            IF v_payment.status<>'RECEIVED'
                OR NEW.customer_id IS DISTINCT FROM COALESCE(v_adjustment_customer,v_payment.payer_customer_id)
""",
    ),
    (
        "        DECLARE v_payment app.payments%ROWTYPE;\n"
        "        BEGIN\n"
        "            PERFORM app.serialize_payment_state(NEW.source_payment_id);",
        "        DECLARE v_payment app.payments%ROWTYPE; v_adjustment_customer uuid;\n"
        "        BEGIN\n"
        "            PERFORM app.serialize_payment_state(NEW.source_payment_id);",
    ),
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Credit excess source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE app.invoice_credit_excess_releases (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            invoice_adjustment_id uuid NOT NULL REFERENCES app.invoice_adjustments(id) ON DELETE RESTRICT,
            source_kind text NOT NULL CHECK(source_kind IN ('PAYMENT_ALLOCATION','CREDIT_APPLICATION')),
            reversed_payment_allocation_id uuid UNIQUE
                REFERENCES app.payment_allocations(id) ON DELETE RESTRICT,
            reversed_credit_application_id uuid UNIQUE
                REFERENCES app.customer_credit_applications(id) ON DELETE RESTRICT,
            replacement_payment_allocation_id uuid UNIQUE
                REFERENCES app.payment_allocations(id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            replacement_credit_application_id uuid UNIQUE
                REFERENCES app.customer_credit_applications(id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            customer_credit_id uuid UNIQUE
                REFERENCES app.customer_credits(id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            released_usd_cents bigint NOT NULL CHECK(released_usd_cents BETWEEN 1 AND 9000000000000000),
            reason text NOT NULL CHECK(reason='{REASON}'),
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL CHECK(isfinite(created_at)),
            CONSTRAINT invoice_credit_excess_release_shape CHECK(
                (source_kind='PAYMENT_ALLOCATION' AND reversed_payment_allocation_id IS NOT NULL
                    AND reversed_credit_application_id IS NULL AND replacement_credit_application_id IS NULL
                    AND customer_credit_id IS NOT NULL)
                OR (source_kind='CREDIT_APPLICATION' AND reversed_credit_application_id IS NOT NULL
                    AND reversed_payment_allocation_id IS NULL AND replacement_payment_allocation_id IS NULL
                    AND customer_credit_id IS NULL))
        );
        CREATE INDEX invoice_credit_excess_releases_adjustment_idx
            ON app.invoice_credit_excess_releases(invoice_adjustment_id,created_at,id);
        CREATE TRIGGER invoice_credit_excess_releases_immutable BEFORE UPDATE OR DELETE
            ON app.invoice_credit_excess_releases FOR EACH ROW
            EXECUTE FUNCTION app.reject_invoice_append_only_mutation();
        CREATE TRIGGER invoice_credit_excess_releases_no_truncate BEFORE TRUNCATE
            ON app.invoice_credit_excess_releases FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_invoice_append_only_mutation();

        CREATE FUNCTION app.validate_invoice_credit_excess_release()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_invoice uuid; v_on_line bigint; v_line uuid;
        BEGIN
            SELECT invoice_id,invoice_line_id INTO v_invoice,v_line FROM app.invoice_adjustments
            WHERE id=NEW.invoice_adjustment_id AND adjustment_type='CREDIT';
            IF NEW.source_kind='PAYMENT_ALLOCATION' THEN
                SELECT detail.posted_amount_usd_cents INTO v_on_line
                FROM app.payment_allocations allocation
                JOIN app.payment_allocation_details detail ON detail.payment_allocation_id=allocation.id
                JOIN app.payment_allocation_reversals reversal ON reversal.payment_allocation_id=allocation.id
                WHERE allocation.id=NEW.reversed_payment_allocation_id AND allocation.invoice_id=v_invoice
                  AND detail.invoice_line_id=v_line AND reversal.reason=NEW.reason;
            ELSE
                SELECT detail.applied_amount_usd_cents INTO v_on_line
                FROM app.customer_credit_applications application
                JOIN app.customer_credit_application_details detail
                    ON detail.customer_credit_application_id=application.id
                JOIN app.customer_credit_application_reversals reversal
                    ON reversal.credit_application_id=application.id
                WHERE application.id=NEW.reversed_credit_application_id AND application.invoice_id=v_invoice
                  AND detail.invoice_line_id=v_line AND reversal.reason=NEW.reason;
            END IF;
            IF v_invoice IS NULL OR v_on_line IS NULL OR NEW.released_usd_cents>v_on_line THEN
                RAISE EXCEPTION 'Credit excess release does not match its reversed source'
                    USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER invoice_credit_excess_releases_validate BEFORE INSERT
            ON app.invoice_credit_excess_releases FOR EACH ROW
            EXECUTE FUNCTION app.validate_invoice_credit_excess_release();

        -- A strictly later instant than every financial event of the Invoice (and Credit).
        CREATE FUNCTION app.credit_excess_instant(p_invoice uuid,p_credit uuid)
        RETURNS timestamptz LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT GREATEST(clock_timestamp(),
                COALESCE(app.allocation_target_latest_at('INVOICE',p_invoice),'-infinity')
                    +interval '1 microsecond',
                COALESCE((SELECT app.credit_latest_at(p_credit) WHERE p_credit IS NOT NULL),'-infinity')
                    +interval '1 microsecond',
                (SELECT updated_at FROM app.invoices WHERE id=p_invoice))
        $$;

        -- Phase 1: reverse whole applications on the line, newest first, until the excess is covered.
        CREATE FUNCTION app.reverse_line_value_for_credit_excess(p_invoice uuid,p_line uuid,
            p_excess bigint,p_actor uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_source record; v_remaining bigint:=p_excess; v_release bigint; v_plan jsonb:='[]'::jsonb;
        BEGIN
            FOR v_source IN
                SELECT 'PAYMENT_ALLOCATION'::text AS kind,allocation.id,NULL::uuid AS credit_id,
                    detail.posted_amount_usd_cents AS on_line,allocation.posted_at AS at
                FROM app.payment_allocation_details detail
                JOIN app.payment_allocations allocation ON allocation.id=detail.payment_allocation_id
                WHERE detail.invoice_line_id=p_line AND allocation.invoice_id=p_invoice
                  AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                      WHERE reversal.payment_allocation_id=allocation.id)
                UNION ALL
                SELECT 'CREDIT_APPLICATION',application.id,application.customer_credit_id,
                    detail.applied_amount_usd_cents,application.occurred_at
                FROM app.customer_credit_application_details detail
                JOIN app.customer_credit_applications application
                    ON application.id=detail.customer_credit_application_id
                WHERE detail.invoice_line_id=p_line AND application.invoice_id=p_invoice
                  AND NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal
                      WHERE reversal.credit_application_id=application.id)
                ORDER BY at DESC,id DESC
            LOOP
                EXIT WHEN v_remaining<=0;
                v_release:=LEAST(v_source.on_line,v_remaining);
                IF v_source.kind='PAYMENT_ALLOCATION' THEN
                    INSERT INTO app.payment_allocation_reversals(id,payment_allocation_id,reason,
                        occurred_at,actor_id,authorization_reference)
                    VALUES(gen_random_uuid(),v_source.id,'{REASON}',
                        app.credit_excess_instant(p_invoice,NULL),p_actor,'payments.allocations.reverse');
                ELSE
                    INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,reason,
                        occurred_at,actor_id,authorization_reference)
                    VALUES(gen_random_uuid(),v_source.id,'{REASON}',
                        app.credit_excess_instant(p_invoice,v_source.credit_id),p_actor,
                        'credits.applications.reverse');
                END IF;
                v_plan:=v_plan||jsonb_build_array(jsonb_build_object('kind',v_source.kind,
                    'id',v_source.id,'released_usd_cents',v_release));
                v_remaining:=v_remaining-v_release;
            END LOOP;
            IF v_remaining>0 THEN
                RAISE EXCEPTION 'Credit excess exceeds the applied value of the line' USING ERRCODE='23514';
            END IF;
            RETURN v_plan;
        END $$;

        -- Phase 2: re-post the unreleased remainder and recognize released Payment value as Credit.
        CREATE FUNCTION app.repost_line_value_after_credit_excess(p_invoice uuid,p_line uuid,
            p_plan jsonb,p_actor uuid,p_adjustment uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_item jsonb; v_released bigint; v_new uuid; v_batch uuid; v_at timestamptz;
            v_credit uuid; v_invoice app.invoices%ROWTYPE; v_allocation app.payment_allocations%ROWTYPE;
            v_application app.customer_credit_applications%ROWTYPE;
            v_credit_total bigint:=0; v_returned bigint:=0; v_credit_ids jsonb:='[]'::jsonb;
            v_trace jsonb; v_remaining_amount bigint;
        BEGIN
            FOR v_item IN SELECT value FROM jsonb_array_elements(p_plan) LOOP
                v_released:=(v_item->>'released_usd_cents')::bigint;
                SELECT * INTO STRICT v_invoice FROM app.invoices WHERE id=p_invoice;
                IF v_item->>'kind'='PAYMENT_ALLOCATION' THEN
                    SELECT * INTO STRICT v_allocation FROM app.payment_allocations
                    WHERE id=(v_item->>'id')::uuid;
                    v_remaining_amount:=v_allocation.amount_usd_cents-v_released;
                    v_new:=CASE WHEN v_remaining_amount>0 THEN gen_random_uuid() END;
                    v_credit:=gen_random_uuid();
                    INSERT INTO app.invoice_credit_excess_releases(id,invoice_adjustment_id,source_kind,
                        reversed_payment_allocation_id,replacement_payment_allocation_id,customer_credit_id,
                        released_usd_cents,reason,actor_id,created_at)
                    VALUES(gen_random_uuid(),p_adjustment,'PAYMENT_ALLOCATION',v_allocation.id,v_new,
                        v_credit,v_released,'{REASON}',p_actor,clock_timestamp());
                    IF v_new IS NOT NULL THEN
                        v_at:=app.credit_excess_instant(p_invoice,NULL);
                        v_batch:=CASE WHEN v_allocation.proposal_batch_id IS NULL THEN NULL
                            ELSE gen_random_uuid() END;
                        INSERT INTO app.payment_allocations(id,payment_id,target_customer_id,proposal_batch_id,
                            between_invoice_sequence,target_kind,invoice_id,late_payment_charge_id,amount_usd_cents,
                            between_invoice_basis,within_invoice_basis,customer_designation_reference,
                            selected_invoice_due_date,selected_invoice_issued_at,selected_invoice_number_snapshot,
                            proposal_generated_at,proposal_trace,posted_at,posted_by,authorization_reference)
                        VALUES(v_new,v_allocation.payment_id,v_allocation.target_customer_id,v_batch,
                            CASE WHEN v_batch IS NULL THEN NULL ELSE 1 END,'INVOICE',p_invoice,NULL,
                            v_remaining_amount,v_allocation.between_invoice_basis,v_allocation.within_invoice_basis,
                            v_allocation.customer_designation_reference,
                            CASE WHEN v_batch IS NULL THEN NULL ELSE v_invoice.due_date END,
                            CASE WHEN v_batch IS NULL THEN NULL ELSE v_invoice.issued_at END,
                            CASE WHEN v_batch IS NULL THEN NULL ELSE v_invoice.invoice_number END,
                            CASE WHEN v_batch IS NULL THEN NULL ELSE v_at END,
                            CASE WHEN v_batch IS NULL THEN NULL ELSE jsonb_build_object('reason','{REASON}',
                                'replaces_payment_allocation_id',v_allocation.id,
                                'invoice_adjustment_id',p_adjustment) END,
                            v_at,p_actor,'payments.allocate');
                        INSERT INTO app.payment_allocation_details(id,payment_allocation_id,invoice_line_id,
                            late_payment_charge_id,obligation_kind,invoice_line_category_snapshot,
                            proposed_amount_usd_cents,posted_amount_usd_cents,attribution_basis,detail_sequence,
                            calculation_trace)
                        SELECT gen_random_uuid(),v_new,kept.invoice_line_id,NULL,kept.obligation_kind,
                            kept.invoice_line_category_snapshot,
                            CASE WHEN v_batch IS NULL THEN NULL ELSE kept.amount END,kept.amount,
                            kept.attribution_basis,
                            (row_number() OVER (ORDER BY kept.detail_sequence))::smallint,
                            jsonb_build_object('reason','{REASON}','replaces_detail_id',kept.id,
                                'invoice_adjustment_id',p_adjustment)
                        FROM (SELECT detail.*,detail.posted_amount_usd_cents
                                -CASE WHEN detail.invoice_line_id=p_line THEN v_released ELSE 0 END AS amount
                            FROM app.payment_allocation_details detail
                            WHERE detail.payment_allocation_id=v_allocation.id) kept
                        WHERE kept.amount>0;
                    END IF;
                    INSERT INTO app.customer_credits(id,customer_id,source_payment_id,recognized_usd_cents,
                        customer_authorization_reference,recognized_at,recognized_by,reason,authorization_reference)
                    VALUES(v_credit,v_invoice.customer_id,v_allocation.payment_id,v_released,
                        'invoice-adjustment:' || p_adjustment::text,app.credit_excess_instant(p_invoice,NULL),
                        p_actor,'{REASON}','credits.recognize');
                    v_credit_total:=v_credit_total+v_released;
                    v_credit_ids:=v_credit_ids||jsonb_build_array(v_credit);
                ELSE
                    SELECT * INTO STRICT v_application FROM app.customer_credit_applications
                    WHERE id=(v_item->>'id')::uuid;
                    v_remaining_amount:=v_application.amount_usd_cents-v_released;
                    v_new:=CASE WHEN v_remaining_amount>0 THEN gen_random_uuid() END;
                    INSERT INTO app.invoice_credit_excess_releases(id,invoice_adjustment_id,source_kind,
                        reversed_credit_application_id,replacement_credit_application_id,
                        released_usd_cents,reason,actor_id,created_at)
                    VALUES(gen_random_uuid(),p_adjustment,'CREDIT_APPLICATION',v_application.id,v_new,
                        v_released,'{REASON}',p_actor,clock_timestamp());
                    IF v_new IS NOT NULL THEN
                        v_at:=app.credit_excess_instant(p_invoice,v_application.customer_credit_id);
                        SELECT jsonb_build_object('reason','{REASON}',
                            'replaces_credit_application_id',v_application.id,
                            'invoice_adjustment_id',p_adjustment,'amount_usd_cents',v_remaining_amount,
                            'details',jsonb_agg(jsonb_build_object('invoice_line_id',kept.invoice_line_id,
                                'amount_usd_cents',kept.amount,'attribution_basis',kept.attribution_basis)
                                ORDER BY kept.detail_sequence))
                        INTO v_trace
                        FROM (SELECT detail.*,detail.applied_amount_usd_cents
                                -CASE WHEN detail.invoice_line_id=p_line THEN v_released ELSE 0 END AS amount
                            FROM app.customer_credit_application_details detail
                            WHERE detail.customer_credit_application_id=v_application.id) kept
                        WHERE kept.amount>0;
                        INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,invoice_id,
                            late_payment_charge_id,final_settlement_id,amount_usd_cents,within_invoice_basis,
                            customer_designation_reference,proposal_generated_at,proposal_trace,occurred_at,
                            actor_id,authorization_reference)
                        VALUES(v_new,v_application.customer_credit_id,'INVOICE',p_invoice,NULL,NULL,
                            v_remaining_amount,v_application.within_invoice_basis,
                            v_application.customer_designation_reference,
                            CASE WHEN v_application.proposal_trace IS NULL THEN NULL ELSE v_at END,
                            CASE WHEN v_application.proposal_trace IS NULL THEN NULL ELSE v_trace END,
                            v_at,p_actor,'credits.apply');
                        INSERT INTO app.customer_credit_application_details(id,customer_credit_application_id,
                            invoice_line_id,late_payment_charge_id,obligation_kind,invoice_line_category_snapshot,
                            proposed_amount_usd_cents,applied_amount_usd_cents,attribution_basis,detail_sequence,
                            calculation_trace)
                        SELECT gen_random_uuid(),v_new,kept.invoice_line_id,NULL,kept.obligation_kind,
                            kept.invoice_line_category_snapshot,
                            CASE WHEN v_application.proposal_trace IS NULL THEN NULL ELSE kept.amount END,
                            kept.amount,kept.attribution_basis,
                            (row_number() OVER (ORDER BY kept.detail_sequence))::smallint,
                            jsonb_build_object('reason','{REASON}','replaces_detail_id',kept.id,
                                'invoice_adjustment_id',p_adjustment)
                        FROM (SELECT detail.*,detail.applied_amount_usd_cents
                                -CASE WHEN detail.invoice_line_id=p_line THEN v_released ELSE 0 END AS amount
                            FROM app.customer_credit_application_details detail
                            WHERE detail.customer_credit_application_id=v_application.id) kept
                        WHERE kept.amount>0;
                    END IF;
                    v_returned:=v_returned+v_released;
                END IF;
            END LOOP;
            RETURN jsonb_build_object('customer_credit_usd_cents',v_credit_total,
                'customer_credit_ids',v_credit_ids,'returned_to_customer_credit_usd_cents',v_returned,
                'released_sources',p_plan);
        END $$;
    """)
    _patch(ADJUST, ADJUST_REPLACEMENTS)
    _patch("app.audit_payment_allocation_event()", ALLOCATION_AUDIT)
    _patch("app.audit_credit_application_event()", APPLICATION_AUDIT)
    _patch("app.validate_credit_application_source()", APPLICATION_SOURCE)
    _patch("app.validate_credit_recognition()", CREDIT_RECOGNITION)
    op.execute(
        "REVOKE ALL ON TABLE app.invoice_credit_excess_releases "
        "FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
    )
    op.execute(
        "GRANT SELECT ON TABLE app.invoice_credit_excess_releases TO prm_runtime,prm_financial"
    )
    for function in (
        "app.validate_invoice_credit_excess_release()",
        "app.credit_excess_instant(uuid,uuid)",
        "app.reverse_line_value_for_credit_excess(uuid,uuid,bigint,uuid)",
        "app.repost_line_value_after_credit_excess(uuid,uuid,jsonb,uuid,uuid)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Credit Adjustment excess migration is forward-only")
