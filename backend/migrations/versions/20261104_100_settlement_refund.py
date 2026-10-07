# ruff: noqa: E501
"""Post-settlement correction: Refund of a paid wrong charge (V1-056 sub-slice 10c-1b).

BR-SETTLE-013, BR-SETTLE-012, BR-CREDIT-014, BR-CREDIT-008, BR-REFUND-014, BR-INV-045,
BR-AUTH-010; DB-SETTLE-003, DB-SETTLE-005, DB-REFUND-001; owner answer 1 to Q-2026-10-06-36 and
the owner answers to Q-2026-10-07-39.

- A wrong charge that was paid is fixed after closure by a REFUND correction: Staff record a
  SETTLEMENT_CORRECTION draft under final_settlements.prepare with a reason, one Invoice line, the
  amount to remove, a Refund method and a reference note (app.record_settlement_refund_draft);
  only a financial.approve holder confirms it (app.confirm_settlement_refund).
- The confirmation writes, each record linked to the correction before it is written, the
  release of the paid part in the order of migration 67 (newest first: a Payment allocation is
  reversed, its unreleased rest re-posted and the released value recognized as Customer Credit
  of the Invoice Customer; a Credit application is reversed and its unreleased rest re-posted, so
  the value returns to its Credit), the credit Adjustment of the line, and one Credit Refund per
  released source, paid to that Credit's Customer. An unpaid part in the same amount is removed
  with it.
- app.settlement_correction_refund_details (append-only; owner answer 1 to Q-2026-10-07-39) keeps
  each such Refund's correction, draft, Refund method and reference note (BR-REFUND-014); no role
  may read or write it.
- Relaxing: the Refund source checks accept a Credit Refund to a Customer other than the payer when
  it is linked to a correction confirmed in this transaction whose own Adjustment released that
  Credit (BR-CREDIT-014, as sub-slice 8f).
- Approved tightening (owner answer 2 to Q-2026-10-07-39): the one-call reversal of a Credit
  application that re-posts the remainder of a Settlement Credit application is refused (P5S01)
  unless it is linked to a correction of that Settlement. Such a row exists only through a
  correction, so this refuses nothing staff can do today.
- An Invoice that a Deposit application paid stays refused until sub-slice 10c-2.
"""

from alembic import op
from sqlalchemy import text

revision = "20261104_100"
down_revision = "20261103_99"
branch_labels = None
depends_on = None

RECORD = "app.record_settlement_refund_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_refund(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.reject_settlement_correction_refund_detail_mutation()",
    "app.validate_settlement_correction_refund_detail()",
    "app.assert_settlement_correction_refund_detail()",
    "app.settlement_correction_refund_allowed(app.refunds)",
    "app.refuse_settlement_credit_application_remainder_reversal()",
    "app.settlement_refund_input(jsonb)",
    "app.settlement_refund_line_sources(uuid,uuid)",
    "app.settlement_refund_source_state(uuid,uuid,uuid)",
    "app.settlement_refund_plan(uuid,uuid,jsonb)",
    "app.settlement_refund_result(uuid)",
)
GENERAL_SOURCE = "app.validate_general_refund_source()"
CREDIT_CUSTOMER_CONFIRMED = "app.assert_credit_customer_refund_confirmed()"
# The reason every migration 67 release record carries (its table CHECK).
RELEASE_REASON = "Invoice adjustment credit excess"

GENERAL_SOURCE_REPLACEMENTS = (
    (
        "                    AND NOT app.credit_customer_refund_allowed(NEW))\n",
        "                    AND NOT app.credit_customer_refund_allowed(NEW)\n"
        "                    -- BR-CREDIT-014 (V1-056 sub-slice 10c-1b): or the Refund of a REFUND\n"
        "                    -- correction confirmed in this transaction.\n"
        "                    AND NOT app.settlement_correction_refund_allowed(NEW))\n",
    ),
)
CREDIT_CUSTOMER_CONFIRMED_REPLACEMENTS = (
    (
        "            IF NEW.recipient_customer_id IS NOT DISTINCT FROM v_payer THEN RETURN NULL; END IF;\n",
        "            IF NEW.recipient_customer_id IS NOT DISTINCT FROM v_payer THEN RETURN NULL; END IF;\n"
        "            -- BR-CREDIT-014 (V1-056 sub-slice 10c-1b): a REFUND correction's own Refund.\n"
        "            IF app.settlement_correction_refund_allowed(NEW) THEN RETURN NULL; END IF;\n",
    ),
)

SETTLEMENT_REFUND_SQL = f"""
    -- DB-REFUND-001 (owner answer 1 to Q-2026-10-07-39): the correction, draft, Refund method and
    -- reference note of each Refund a post-settlement correction pays (BR-REFUND-014). Written
    -- before its Refund row (deferred key) so the Refund source check can read it. The Refund row
    -- carries the recipient.
    CREATE TABLE app.settlement_correction_refund_details (
        refund_id uuid PRIMARY KEY REFERENCES app.refunds(id) ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED,
        settlement_correction_id uuid NOT NULL
            REFERENCES app.settlement_corrections(id) ON DELETE RESTRICT,
        draft_id uuid NOT NULL REFERENCES app.financial_drafts(id) ON DELETE RESTRICT,
        refund_method_id uuid NOT NULL REFERENCES app.refund_methods(id) ON DELETE RESTRICT,
        reference_note text NOT NULL
            CHECK (reference_note=btrim(reference_note) AND length(reference_note) BETWEEN 1 AND 500),
        recorded_at timestamptz NOT NULL CHECK (isfinite(recorded_at))
    );
    CREATE INDEX settlement_correction_refund_details_correction_idx
        ON app.settlement_correction_refund_details(settlement_correction_id);
    COMMENT ON TABLE app.settlement_correction_refund_details IS
        'Append-only correction, draft, Refund method and reference note of each Refund a post-settlement correction pays (BR-REFUND-014, BR-SETTLE-013); written only by the correction confirms';
    CREATE FUNCTION app.reject_settlement_correction_refund_detail_mutation()
    RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    BEGIN
        RAISE EXCEPTION 'Post-settlement correction Refund details are append-only' USING ERRCODE='55000';
    END $$;
    CREATE TRIGGER settlement_correction_refund_details_immutable BEFORE UPDATE OR DELETE
        ON app.settlement_correction_refund_details FOR EACH ROW
        EXECUTE FUNCTION app.reject_settlement_correction_refund_detail_mutation();
    CREATE TRIGGER settlement_correction_refund_details_no_truncate BEFORE TRUNCATE
        ON app.settlement_correction_refund_details FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_settlement_correction_refund_detail_mutation();

    -- A details row belongs to a correction confirmed in this same transaction, with its own draft
    -- (the rule of the correction effects, sub-slice 10a), and its Refund is already linked to that
    -- correction (the writer links before it writes; security review round 1).
    CREATE FUNCTION app.validate_settlement_correction_refund_detail()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
        IF NOT EXISTS(SELECT 1 FROM app.settlement_corrections correction
            JOIN app.financial_draft_decisions decision
                ON decision.draft_id=correction.correlation_id AND decision.decision='CONFIRMED'
            WHERE correction.id=NEW.settlement_correction_id AND correction.correlation_id=NEW.draft_id
              AND decision.result->>'transaction_id'=pg_current_xact_id()::text
              AND decision.decided_at>=transaction_timestamp()
              AND EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                  WHERE effect.settlement_correction_id=correction.id AND effect.refund_id=NEW.refund_id))
        THEN RAISE EXCEPTION 'A post-settlement correction Refund detail is written with its correction'
            USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER settlement_correction_refund_details_validate BEFORE INSERT
        ON app.settlement_correction_refund_details FOR EACH ROW
        EXECUTE FUNCTION app.validate_settlement_correction_refund_detail();

    -- BR-AUTH-010 at commit: the Refund a details row describes was processed by the correction's
    -- approver (as the sub-slice 8d details check; security review round 1).
    CREATE FUNCTION app.assert_settlement_correction_refund_detail()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
        IF NOT EXISTS(SELECT 1 FROM app.refunds refund
            JOIN app.settlement_corrections correction ON correction.id=NEW.settlement_correction_id
            WHERE refund.id=NEW.refund_id AND refund.processed_by=correction.actor_id)
        THEN RAISE EXCEPTION 'A post-settlement correction Refund is processed by the correction''s approver'
            USING ERRCODE='42501'; END IF;
        RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER settlement_correction_refund_details_approver
        AFTER INSERT ON app.settlement_correction_refund_details
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION app.assert_settlement_correction_refund_detail();

    -- BR-CREDIT-014: whether a Credit Refund is the own Refund of a REFUND correction confirmed in
    -- this transaction: its details row names that correction and its draft, the correction's
    -- approver processed it, it is linked to that same correction, it pays its Credit's own
    -- Customer, and together with the correction's other Refunds of that Credit it is within what
    -- that correction's own Adjustment released to that Credit (a released allocation's new
    -- Credit, or the Credit of a reversed Credit application; security review round 1). Never
    -- NULL.
    CREATE FUNCTION app.settlement_correction_refund_allowed(p_refund app.refunds)
    RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((SELECT (p_refund).recipient_customer_id IS NOT DISTINCT FROM credit.customer_id
                AND correction.actor_id=(p_refund).processed_by
                AND app.settlement_correction_linked(correction.final_settlement_id,'refunds',(p_refund).id)
                AND EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                    WHERE effect.settlement_correction_id=correction.id
                      AND effect.refund_id=(p_refund).id)
                AND (p_refund).usd_accounting_value_cents+(
                    SELECT COALESCE(sum(other.usd_accounting_value_cents),0)
                    FROM app.settlement_correction_effects effect
                    JOIN app.refunds other ON other.id=effect.refund_id
                    WHERE effect.settlement_correction_id=correction.id
                      AND other.source_customer_credit_id=credit.id AND other.id<>(p_refund).id)<=(
                    SELECT COALESCE(sum(release.released_usd_cents),0)
                    FROM app.settlement_correction_effects effect
                    JOIN app.invoice_credit_excess_releases release
                        ON release.invoice_adjustment_id=effect.invoice_adjustment_id
                    LEFT JOIN app.customer_credit_applications application
                        ON application.id=release.reversed_credit_application_id
                    WHERE effect.settlement_correction_id=correction.id
                      AND (release.customer_credit_id=credit.id
                          OR application.customer_credit_id=credit.id))
            FROM app.settlement_correction_refund_details detail
            JOIN app.settlement_corrections correction
                ON correction.id=detail.settlement_correction_id AND correction.correlation_id=detail.draft_id
            JOIN app.customer_credits credit ON credit.id=(p_refund).source_customer_credit_id
            WHERE detail.refund_id=(p_refund).id),false)
    $$;

    -- Owner answer 2 to Q-2026-10-07-39 (approved tightening): a Credit application that re-posts,
    -- directly or through earlier re-posts, the remainder of a Settlement Credit application is
    -- still money the closed Settlement relied on; its reversal passes only when it is linked to a
    -- correction of that Settlement confirmed in this transaction (as the 8e-2 refusal).
    CREATE FUNCTION app.refuse_settlement_credit_application_remainder_reversal()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_settlement uuid;
    BEGIN
        WITH RECURSIVE replaced(application_id) AS (
            SELECT release.reversed_credit_application_id FROM app.invoice_credit_excess_releases release
            WHERE release.replacement_credit_application_id=NEW.credit_application_id
            UNION
            SELECT release.reversed_credit_application_id FROM app.invoice_credit_excess_releases release
            JOIN replaced ON release.replacement_credit_application_id=replaced.application_id)
        SELECT application.final_settlement_id INTO v_settlement FROM replaced
        JOIN app.customer_credit_applications application ON application.id=replaced.application_id
        WHERE application.final_settlement_id IS NOT NULL LIMIT 1;
        IF v_settlement IS NOT NULL AND app.settlement_correction_linked(v_settlement,
            'customer_credit_application_reversals',NEW.id) IS NOT TRUE
        THEN RAISE EXCEPTION 'A Final Settlement Credit application changes only through a post-settlement correction'
            USING ERRCODE='P5S01'; END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER a0_customer_credit_application_reversals_settlement_remainder BEFORE INSERT
        ON app.customer_credit_application_reversals FOR EACH ROW
        EXECUTE FUNCTION app.refuse_settlement_credit_application_remainder_reversal();

    -- The draft's Refund correction, checked for shape only and stored in one form: malformed
    -- input 22023.
    CREATE FUNCTION app.settlement_refund_input(p_refund jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_invoice text; v_line text; v_method text;
    BEGIN
        IF p_refund IS NULL OR jsonb_typeof(p_refund) IS DISTINCT FROM 'object'
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_refund) key
                WHERE key NOT IN ('invoice_id','invoice_line_id','amount_usd_cents','refund_method_id',
                    'reference_note'))
        THEN RAISE EXCEPTION 'Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        v_invoice:=app.final_settlement_plan_id(p_refund->'invoice_id');
        v_line:=app.final_settlement_plan_id(p_refund->'invoice_line_id');
        v_method:=app.final_settlement_plan_id(p_refund->'refund_method_id');
        IF v_invoice IS NULL OR v_line IS NULL OR v_method IS NULL
            OR jsonb_typeof(p_refund->'amount_usd_cents') IS DISTINCT FROM 'number'
            OR (p_refund->>'amount_usd_cents') !~ '^[1-9][0-9]{{0,15}}$'
            OR jsonb_typeof(p_refund->'reference_note') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_refund->>'reference_note',500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        -- The cap of the other money writers; a JSON number always casts.
        IF (p_refund->>'amount_usd_cents')::numeric>9000000000000000 THEN
            RAISE EXCEPTION 'Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        RETURN jsonb_build_object('invoice_id',v_invoice,'invoice_line_id',v_line,
            'amount_usd_cents',(p_refund->>'amount_usd_cents')::bigint,'refund_method_id',v_method,
            'reference_note',p_refund->>'reference_note');
    END $$;

    -- The Payment allocations and Credit applications that pay the line now, in the release order
    -- of migration 67 (newest first), with the Payment, the Credit, the Customer the released
    -- value belongs to (the Invoice Customer for an allocation, BR-CREDIT-014; the Credit's
    -- Customer for an application, BR-CREDIT-008) and the payer.
    CREATE FUNCTION app.settlement_refund_line_sources(p_invoice uuid,p_line uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT COALESCE(jsonb_agg(jsonb_build_object('kind',source.kind,'id',source.id,
                'on_line_usd_cents',source.on_line,'at',source.at,'payment_id',source.payment_id,
                'credit_id',source.credit_id,'recipient_customer_id',source.recipient,
                'payer_customer_id',payment.payer_customer_id)
            ORDER BY source.at DESC,source.id DESC),'[]'::jsonb)
        FROM (
            SELECT 'PAYMENT_ALLOCATION'::text AS kind,allocation.id,
                detail.posted_amount_usd_cents AS on_line,allocation.posted_at AS at,
                allocation.payment_id,NULL::uuid AS credit_id,invoice.customer_id AS recipient
            FROM app.payment_allocation_details detail
            JOIN app.payment_allocations allocation ON allocation.id=detail.payment_allocation_id
            JOIN app.invoices invoice ON invoice.id=allocation.invoice_id
            WHERE detail.invoice_line_id=p_line AND allocation.invoice_id=p_invoice
              AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                  WHERE reversal.payment_allocation_id=allocation.id)
            UNION ALL
            SELECT 'CREDIT_APPLICATION',application.id,detail.applied_amount_usd_cents,
                application.occurred_at,credit.source_payment_id,credit.id,credit.customer_id
            FROM app.customer_credit_application_details detail
            JOIN app.customer_credit_applications application
                ON application.id=detail.customer_credit_application_id
            JOIN app.customer_credits credit ON credit.id=application.customer_credit_id
            WHERE detail.invoice_line_id=p_line AND application.invoice_id=p_invoice
              AND NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal
                  WHERE reversal.credit_application_id=application.id)
        ) source
        JOIN app.payments payment ON payment.id=source.payment_id
    $$;

    -- The state a Refund correction depends on; its digest is the draft's source revision: the
    -- charge reduction's state (the closure, the Invoice, the line's obligation and paid value)
    -- and every source that pays the line now.
    CREATE FUNCTION app.settlement_refund_source_state(p_settlement uuid,p_invoice uuid,p_line uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT app.settlement_charge_reduction_source_state(p_settlement,p_invoice,p_line)
            || jsonb_build_object('sources',app.settlement_refund_line_sources(p_invoice,p_line))
    $$;

    -- Checks a stored-form Refund correction against the current state and returns what the draft
    -- records: the Lease, the Invoice's Customer, the correction, the sources it releases (in the
    -- release order, each with its released amount) and the source revision. An unknown
    -- Settlement, Invoice or line P0002; a state the correction does not allow 55000.
    CREATE FUNCTION app.settlement_refund_plan(p_property uuid,p_settlement uuid,p_refund jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_settlement app.final_settlements%ROWTYPE; v_invoice app.invoices%ROWTYPE; v_line uuid;
        v_amount bigint; v_remaining bigint; v_release bigint; v_source jsonb;
        v_released jsonb:='[]'::jsonb;
    BEGIN
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        SELECT * INTO v_invoice FROM app.invoices
        WHERE id=(p_refund->>'invoice_id')::uuid AND lease_id=v_settlement.lease_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The corrected Invoice is not an Invoice of this Final Settlement'
                USING ERRCODE='P0002'; END IF;
        IF v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID','PAID') THEN
            RAISE EXCEPTION 'The corrected Invoice is not an issued obligation of this Final Settlement'
                USING ERRCODE='55000'; END IF;
        SELECT line.id INTO v_line FROM app.invoice_lines line
        WHERE line.id=(p_refund->>'invoice_line_id')::uuid AND line.invoice_id=v_invoice.id;
        IF NOT FOUND THEN RAISE EXCEPTION 'Invoice line was not found' USING ERRCODE='P0002'; END IF;
        -- 8a-1: an Invoice that a Deposit application paid takes no Adjustment (until 10c-2).
        IF EXISTS(SELECT 1 FROM app.deposit_applications application
            WHERE application.invoice_id=v_invoice.id)
        THEN RAISE EXCEPTION 'A Deposit application paid this obligation at Final Settlement'
            USING ERRCODE='55000'; END IF;
        v_amount:=(p_refund->>'amount_usd_cents')::bigint;
        IF v_amount>app.invoice_adjusted_line_obligation(v_line) THEN
            RAISE EXCEPTION 'The Refund correction exceeds the charge on the line'
                USING ERRCODE='55000'; END IF;
        -- Design note: a REFUND always pays a Refund; removing only unpaid value is a reduction.
        v_remaining:=v_amount-app.invoice_line_outstanding(v_line);
        IF v_remaining<=0 THEN
            RAISE EXCEPTION 'The Refund correction releases no paid value; an unpaid charge is removed by a charge reduction'
                USING ERRCODE='55000'; END IF;
        -- BR-REFUND-014: an active Refund method (as the Final Settlement draft).
        PERFORM 1 FROM app.refund_methods WHERE id=(p_refund->>'refund_method_id')::uuid AND active;
        IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
        -- The release of migration 67: whole sources, newest first, until the paid part is covered.
        FOR v_source IN SELECT value FROM jsonb_array_elements(
            app.settlement_refund_line_sources(v_invoice.id,v_line))
        LOOP
            EXIT WHEN v_remaining<=0;
            v_release:=LEAST((v_source->>'on_line_usd_cents')::bigint,v_remaining);
            v_released:=v_released||jsonb_build_array((v_source-'on_line_usd_cents'-'at')
                ||jsonb_build_object('released_usd_cents',v_release));
            v_remaining:=v_remaining-v_release;
        END LOOP;
        IF v_remaining>0 THEN
            RAISE EXCEPTION 'Credit excess exceeds the applied value of the line' USING ERRCODE='23514';
        END IF;
        RETURN jsonb_build_object('lease_id',v_settlement.lease_id,'customer_id',v_invoice.customer_id,
            'refund',p_refund,'released_sources',v_released,
            'source_revision','settlement-correction:' || encode(sha256(convert_to(
                app.settlement_refund_source_state(p_settlement,v_invoice.id,v_line)::text,
                'UTF8')),'hex'));
    END $$;

    -- Staff record a Refund correction draft (final_settlements.prepare); it has no financial
    -- effect until a financial.approve holder confirms it.
    CREATE FUNCTION app.record_settlement_refund_draft(p_property uuid,p_actor uuid,p_draft uuid,
        p_settlement uuid,p_refund jsonb,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_plan jsonb; v_payload jsonb;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The reason is at most 500 characters: the Adjustment keeps it (as app.adjust_invoice).
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=app.settlement_refund_input(p_refund);
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='REFUND' AND v_existing.prepared_by=p_actor
                AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND v_existing.payload->'refund'=v_input
            -- The decision's transaction id never leaves the database (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{{decision,result,transaction_id}}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        v_plan:=app.settlement_refund_plan(p_property,p_settlement,v_input);
        v_payload:=jsonb_build_object('variant','REFUND','final_settlement_id',p_settlement,
            'lease_id',v_plan->'lease_id','customer_id',v_plan->'customer_id',
            'refund',v_plan->'refund','released_sources',v_plan->'released_sources');
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,v_plan->>'source_revision',p_reason);
    END $$;

    -- What the confirm returns, also for an exact repeat (rebuilt from the stored records): the
    -- draft without the decision's transaction id, the correction header, the linked Adjustment,
    -- the released sources (from the Adjustment's release records), the Refunds with their method
    -- and note, and the Invoice as it is now.
    CREATE FUNCTION app.settlement_refund_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        WITH adjustment AS (
            SELECT adjustment.* FROM app.settlement_correction_effects effect
            JOIN app.invoice_adjustments adjustment ON adjustment.id=effect.invoice_adjustment_id
            WHERE effect.settlement_correction_id=app.settlement_correction_id(p_draft))
        SELECT jsonb_build_object(
            'draft',app.financial_draft_json(draft) #- '{{decision,result,transaction_id}}',
            'settlement_correction',(SELECT jsonb_build_object('id',correction.id,
                    'final_settlement_id',correction.final_settlement_id,'reason',correction.reason,
                    'occurred_at',correction.occurred_at,'actor_id',correction.actor_id,
                    'authorization_reference',correction.authorization_reference)
                FROM app.settlement_corrections correction
                WHERE correction.id=app.settlement_correction_id(draft.id)),
            'invoice_adjustment',(SELECT jsonb_build_object('id',adjustment.id,
                    'invoice_id',adjustment.invoice_id,'invoice_line_id',adjustment.invoice_line_id,
                    'adjustment_type',adjustment.adjustment_type,
                    'amount_usd_cents',adjustment.amount_usd_cents,
                    'source_reference',adjustment.source_reference,'reason',adjustment.reason,
                    'occurred_at',adjustment.occurred_at,'actor_id',adjustment.actor_id,
                    'authorization_reference',adjustment.authorization_reference)
                FROM adjustment),
            'released_sources',(SELECT COALESCE(jsonb_agg(jsonb_build_object(
                    'source_kind',release.source_kind,
                    'reversed_payment_allocation_id',release.reversed_payment_allocation_id,
                    'reversed_credit_application_id',release.reversed_credit_application_id,
                    'replacement_payment_allocation_id',release.replacement_payment_allocation_id,
                    'replacement_credit_application_id',release.replacement_credit_application_id,
                    'customer_credit_id',COALESCE(release.customer_credit_id,application.customer_credit_id),
                    'released_usd_cents',release.released_usd_cents)
                    ORDER BY release.created_at,release.id),'[]'::jsonb)
                FROM app.invoice_credit_excess_releases release
                LEFT JOIN app.customer_credit_applications application
                    ON application.id=release.reversed_credit_application_id
                WHERE release.invoice_adjustment_id=(SELECT id FROM adjustment)),
            'refunds',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',refund.id,
                    'refund_number',refund.refund_number,
                    'recipient_customer_id',refund.recipient_customer_id,
                    'source_customer_credit_id',refund.source_customer_credit_id,
                    'amount_usd_cents',refund.usd_accounting_value_cents,
                    'refund_method_id',detail.refund_method_id,'reference_note',detail.reference_note,
                    'reason',refund.reason,'processed_at',refund.processed_at,
                    'processed_by',refund.processed_by,
                    'authorization_reference',refund.authorization_reference)
                    ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.refunds refund ON refund.id=effect.refund_id
                JOIN app.settlement_correction_refund_details detail ON detail.refund_id=refund.id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)),
            'invoice',app.invoice_resource_snapshot((SELECT invoice_id FROM adjustment)))
        FROM app.financial_drafts draft WHERE draft.id=p_draft
    $$;

    -- A financial.approve holder confirms a Refund correction. Refusals: an unknown Property,
    -- draft or Settlement P0002/P4501; an inactive or missing approver P4506 or 42501; business
    -- state (a decided draft, an open Settlement, an inactive Refund method) 55000; a draft whose
    -- sources changed since it was recorded P5S02 (stale; it stays pending). Nothing is written
    -- unless everything succeeds.
    CREATE FUNCTION app.confirm_settlement_refund(p_property uuid,p_actor uuid,p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_invoice app.invoices%ROWTYPE; v_timezone text; v_now timestamptz; v_business_date date;
        v_refund jsonb; v_plan jsonb; v_correction uuid; v_adjustment uuid; v_line uuid;
        v_amount bigint; v_method uuid; v_reference text; v_unit uuid; v_before jsonb;
        v_after jsonb; v_evidence jsonb; v_result jsonb; v_source jsonb; v_lock uuid;
        v_released bigint; v_new uuid; v_credit uuid; v_recipient uuid; v_batch uuid;
        v_at timestamptz; v_trace jsonb; v_rest bigint; v_refund_id uuid;
        v_allocation app.payment_allocations%ROWTYPE;
        v_application app.customer_credit_applications%ROWTYPE;
        v_paid jsonb:='[]'::jsonb; v_refunds jsonb:='[]'::jsonb;
    BEGIN
        v_timezone:=app.require_invoice_command_actor(p_property,p_actor);
        -- BR-AUTH-010: a person confirms; an inactive approver is refused above (P4506).
        IF NOT EXISTS(SELECT 1 FROM app.actor_identities identity
            WHERE identity.actor_id=p_actor AND identity.identity_kind='HUMAN')
        THEN RAISE EXCEPTION 'A post-settlement correction is confirmed only by a human approver'
            USING ERRCODE='42501'; END IF;
        IF p_authorization IS DISTINCT FROM 'financial.approve' THEN
            RAISE EXCEPTION 'Only financial.approve may confirm a post-settlement correction'
                USING ERRCODE='42501'; END IF;
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' THEN
            RAISE EXCEPTION 'Post-settlement correction input is invalid' USING ERRCODE='22023'; END IF;
        -- The serialization of every decision on this draft, then the replay of an exact repeat.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        IF EXISTS(SELECT 1 FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
            WHERE draft.id=p_draft AND draft.property_id=p_property AND draft.kind='SETTLEMENT_CORRECTION'
              AND draft.payload->>'variant'='REFUND' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_refund_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'REFUND'
        THEN RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        IF EXISTS(SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=p_draft) THEN
            RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE='55000'; END IF;
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=app.final_settlement_plan_id(v_draft.payload->'final_settlement_id')::uuid
          AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        -- The checks below rely on READ COMMITTED: each statement sees the commits the locks
        -- waited for (as the other correction confirms).
        IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
            RAISE EXCEPTION 'A post-settlement correction is confirmed at READ COMMITTED'
                USING ERRCODE='55000'; END IF;
        -- The stored correction passes the recorder's shape check again (as sub-slice 10c-1a).
        v_refund:=app.settlement_refund_input(v_draft.payload->'refund');
        IF v_refund IS DISTINCT FROM v_draft.payload->'refund' THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_line:=(v_refund->>'invoice_line_id')::uuid;
        v_amount:=(v_refund->>'amount_usd_cents')::bigint;
        v_method:=(v_refund->>'refund_method_id')::uuid;
        -- Lock order: the draft lock (above); the Settlement's draft lock (as
        -- app.begin_settlement_correction takes it); each source Payment and then each source
        -- Credit, in id order, as the allocation, Credit application and Refund writers take a
        -- Payment, then its Credit, then the Invoice; the Invoice; then the Settlement row in
        -- app.begin_settlement_correction (the 8e-1 refusal's order: Invoice, then Settlement row).
        -- A source added after the draft is not locked here, but it changes the source revision,
        -- so the draft is stale below.
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        FOR v_lock IN SELECT DISTINCT app.final_settlement_plan_id(source->'payment_id')::uuid
            FROM jsonb_array_elements(CASE WHEN jsonb_typeof(v_draft.payload->'released_sources')='array'
                THEN v_draft.payload->'released_sources' ELSE '[]'::jsonb END) source
            WHERE app.final_settlement_plan_id(source->'payment_id') IS NOT NULL ORDER BY 1
        LOOP
            PERFORM app.serialize_payment_state(v_lock);
            PERFORM 1 FROM app.payments WHERE id=v_lock FOR UPDATE;
        END LOOP;
        FOR v_lock IN SELECT DISTINCT app.final_settlement_plan_id(source->'credit_id')::uuid
            FROM jsonb_array_elements(CASE WHEN jsonb_typeof(v_draft.payload->'released_sources')='array'
                THEN v_draft.payload->'released_sources' ELSE '[]'::jsonb END) source
            WHERE app.final_settlement_plan_id(source->'credit_id') IS NOT NULL ORDER BY 1
        LOOP
            PERFORM 1 FROM app.customer_credits WHERE id=v_lock FOR UPDATE;
        END LOOP;
        SELECT * INTO v_invoice FROM app.invoices WHERE id=(v_refund->>'invoice_id')::uuid FOR UPDATE;
        -- Under the locks, the sources still have the digest the draft recorded, and the check of
        -- the recorder still gives the same release; otherwise the draft is stale and stays pending.
        IF 'settlement-correction:' || encode(sha256(convert_to(app.settlement_refund_source_state(
                v_settlement.id,(v_refund->>'invoice_id')::uuid,v_line)::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        v_plan:=app.settlement_refund_plan(p_property,v_settlement.id,v_refund);
        IF v_plan->>'source_revision' IS DISTINCT FROM v_draft.source_revision
            OR v_plan->'lease_id' IS DISTINCT FROM v_draft.payload->'lease_id'
            OR v_plan->'customer_id' IS DISTINCT FROM v_draft.payload->'customer_id'
            OR v_plan->'released_sources' IS DISTINCT FROM v_draft.payload->'released_sources'
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        -- BR-REFUND-014: the method stays active until the Refunds are written (as sub-slice 8d).
        PERFORM 1 FROM app.refund_methods WHERE id=v_method AND active FOR SHARE;
        IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
        SELECT lease.unit_id INTO STRICT v_unit FROM app.leases lease WHERE lease.id=v_invoice.lease_id;

        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written, and every id is fresh, never derived from the draft (sub-slice 10b).
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve');
        v_reference:='settlement-correction:' || v_correction::text;
        v_before:=app.invoice_resource_snapshot(v_invoice.id);
        v_evidence:=jsonb_build_object('capability','financial.approve','draft_id',p_draft,
            'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
            'variant','REFUND');
        -- Phase 1 of migration 67: reverse each released source whole, newest first. A Settlement
        -- Credit application's reversal passes the 8e-2 refusal because it is linked first.
        FOR v_source IN SELECT value FROM jsonb_array_elements(v_plan->'released_sources') LOOP
            v_new:=gen_random_uuid();
            IF v_source->>'kind'='PAYMENT_ALLOCATION' THEN
                PERFORM app.link_settlement_correction_effect(v_correction,
                    'payment_allocation_reversal_id',v_new);
                INSERT INTO app.payment_allocation_reversals(id,payment_allocation_id,reason,
                    occurred_at,actor_id,authorization_reference)
                VALUES(v_new,(v_source->>'id')::uuid,'{RELEASE_REASON}',
                    app.credit_excess_instant(v_invoice.id,NULL),p_actor,'payments.allocations.reverse');
            ELSE
                PERFORM app.link_settlement_correction_effect(v_correction,
                    'credit_application_reversal_id',v_new);
                INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,reason,
                    occurred_at,actor_id,authorization_reference)
                VALUES(v_new,(v_source->>'id')::uuid,'{RELEASE_REASON}',
                    app.credit_excess_instant(v_invoice.id,(v_source->>'credit_id')::uuid),p_actor,
                    'credits.applications.reverse');
            END IF;
        END LOOP;
        -- The credit Adjustment after the reversals, as app.adjust_invoice writes it.
        v_now:=app.credit_excess_instant(v_invoice.id,NULL);
        v_business_date:=timezone(v_timezone,v_now)::date;
        v_adjustment:=gen_random_uuid();
        PERFORM app.link_settlement_correction_effect(v_correction,'invoice_adjustment_id',v_adjustment);
        INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,
            amount_usd_cents,source_reference,reason,occurred_at,actor_id,authorization_reference)
        VALUES (v_adjustment,v_invoice.id,v_line,'CREDIT',v_amount,v_reference,v_draft.reason,v_now,
            p_actor,'financial.approve');
        -- Phase 2 of migration 67: re-post each source's unreleased rest; released Payment value
        -- becomes Customer Credit of the Invoice Customer (BR-CREDIT-014) and released Credit value
        -- returns to its Credit.
        FOR v_source IN SELECT value FROM jsonb_array_elements(v_plan->'released_sources') LOOP
            v_released:=(v_source->>'released_usd_cents')::bigint;
            IF v_source->>'kind'='PAYMENT_ALLOCATION' THEN
                SELECT * INTO STRICT v_allocation FROM app.payment_allocations
                WHERE id=(v_source->>'id')::uuid;
                v_rest:=v_allocation.amount_usd_cents-v_released;
                v_new:=CASE WHEN v_rest>0 THEN gen_random_uuid() END;
                v_credit:=gen_random_uuid();
                INSERT INTO app.invoice_credit_excess_releases(id,invoice_adjustment_id,source_kind,
                    reversed_payment_allocation_id,replacement_payment_allocation_id,customer_credit_id,
                    released_usd_cents,reason,actor_id,created_at)
                VALUES(gen_random_uuid(),v_adjustment,'PAYMENT_ALLOCATION',v_allocation.id,v_new,
                    v_credit,v_released,'{RELEASE_REASON}',p_actor,clock_timestamp());
                IF v_new IS NOT NULL THEN
                    v_at:=app.credit_excess_instant(v_invoice.id,NULL);
                    v_batch:=CASE WHEN v_allocation.proposal_batch_id IS NULL THEN NULL
                        ELSE gen_random_uuid() END;
                    PERFORM app.link_settlement_correction_effect(v_correction,'payment_allocation_id',v_new);
                    INSERT INTO app.payment_allocations(id,payment_id,target_customer_id,proposal_batch_id,
                        between_invoice_sequence,target_kind,invoice_id,late_payment_charge_id,amount_usd_cents,
                        between_invoice_basis,within_invoice_basis,customer_designation_reference,
                        selected_invoice_due_date,selected_invoice_issued_at,selected_invoice_number_snapshot,
                        proposal_generated_at,proposal_trace,posted_at,posted_by,authorization_reference)
                    VALUES(v_new,v_allocation.payment_id,v_allocation.target_customer_id,v_batch,
                        CASE WHEN v_batch IS NULL THEN NULL ELSE 1 END,'INVOICE',v_invoice.id,NULL,
                        v_rest,v_allocation.between_invoice_basis,v_allocation.within_invoice_basis,
                        v_allocation.customer_designation_reference,
                        CASE WHEN v_batch IS NULL THEN NULL ELSE v_invoice.due_date END,
                        CASE WHEN v_batch IS NULL THEN NULL ELSE v_invoice.issued_at END,
                        CASE WHEN v_batch IS NULL THEN NULL ELSE v_invoice.invoice_number END,
                        CASE WHEN v_batch IS NULL THEN NULL ELSE v_at END,
                        CASE WHEN v_batch IS NULL THEN NULL ELSE jsonb_build_object(
                            'reason','{RELEASE_REASON}','replaces_payment_allocation_id',v_allocation.id,
                            'invoice_adjustment_id',v_adjustment) END,
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
                        jsonb_build_object('reason','{RELEASE_REASON}','replaces_detail_id',kept.id,
                            'invoice_adjustment_id',v_adjustment)
                    FROM (SELECT detail.*,detail.posted_amount_usd_cents
                            -CASE WHEN detail.invoice_line_id=v_line THEN v_released ELSE 0 END AS amount
                        FROM app.payment_allocation_details detail
                        WHERE detail.payment_allocation_id=v_allocation.id) kept
                    WHERE kept.amount>0;
                END IF;
                INSERT INTO app.customer_credits(id,customer_id,source_payment_id,recognized_usd_cents,
                    customer_authorization_reference,recognized_at,recognized_by,reason,authorization_reference)
                VALUES(v_credit,v_invoice.customer_id,v_allocation.payment_id,v_released,
                    'invoice-adjustment:' || v_adjustment::text,app.credit_excess_instant(v_invoice.id,NULL),
                    p_actor,'{RELEASE_REASON}','credits.recognize');
            ELSE
                SELECT * INTO STRICT v_application FROM app.customer_credit_applications
                WHERE id=(v_source->>'id')::uuid;
                v_rest:=v_application.amount_usd_cents-v_released;
                v_new:=CASE WHEN v_rest>0 THEN gen_random_uuid() END;
                INSERT INTO app.invoice_credit_excess_releases(id,invoice_adjustment_id,source_kind,
                    reversed_credit_application_id,replacement_credit_application_id,
                    released_usd_cents,reason,actor_id,created_at)
                VALUES(gen_random_uuid(),v_adjustment,'CREDIT_APPLICATION',v_application.id,v_new,
                    v_released,'{RELEASE_REASON}',p_actor,clock_timestamp());
                IF v_new IS NOT NULL THEN
                    v_at:=app.credit_excess_instant(v_invoice.id,v_application.customer_credit_id);
                    SELECT jsonb_build_object('reason','{RELEASE_REASON}',
                        'replaces_credit_application_id',v_application.id,
                        'invoice_adjustment_id',v_adjustment,'amount_usd_cents',v_rest,
                        'details',jsonb_agg(jsonb_build_object('invoice_line_id',kept.invoice_line_id,
                            'amount_usd_cents',kept.amount,'attribution_basis',kept.attribution_basis)
                            ORDER BY kept.detail_sequence))
                    INTO v_trace
                    FROM (SELECT detail.*,detail.applied_amount_usd_cents
                            -CASE WHEN detail.invoice_line_id=v_line THEN v_released ELSE 0 END AS amount
                        FROM app.customer_credit_application_details detail
                        WHERE detail.customer_credit_application_id=v_application.id) kept
                    WHERE kept.amount>0;
                    -- The rest is an ordinary Credit application (no Final Settlement link); when it
                    -- re-posts a Settlement Credit application, its one-call reversal stays refused.
                    PERFORM app.link_settlement_correction_effect(v_correction,
                        'customer_credit_application_id',v_new);
                    INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,invoice_id,
                        late_payment_charge_id,final_settlement_id,amount_usd_cents,within_invoice_basis,
                        customer_designation_reference,proposal_generated_at,proposal_trace,occurred_at,
                        actor_id,authorization_reference)
                    VALUES(v_new,v_application.customer_credit_id,'INVOICE',v_invoice.id,NULL,NULL,
                        v_rest,v_application.within_invoice_basis,
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
                        jsonb_build_object('reason','{RELEASE_REASON}','replaces_detail_id',kept.id,
                            'invoice_adjustment_id',v_adjustment)
                    FROM (SELECT detail.*,detail.applied_amount_usd_cents
                            -CASE WHEN detail.invoice_line_id=v_line THEN v_released ELSE 0 END AS amount
                        FROM app.customer_credit_application_details detail
                        WHERE detail.customer_credit_application_id=v_application.id) kept
                    WHERE kept.amount>0;
                END IF;
                v_credit:=v_application.customer_credit_id;
            END IF;
            v_paid:=v_paid||jsonb_build_array(jsonb_build_object('customer_credit_id',v_credit,
                'released_usd_cents',v_released));
        END LOOP;
        -- The Invoice status, version and time follow, as app.adjust_invoice refreshes them.
        UPDATE app.invoices SET status=app.invoice_application_status(v_invoice.id),
            version=version+1,updated_at=GREATEST(v_now,updated_at),updated_by=p_actor
        WHERE id=v_invoice.id;
        -- One Credit Refund per released source, paid to that Credit's Customer (BR-CREDIT-014),
        -- with the draft's method and note in its own details row (BR-REFUND-014; owner answer 1 to
        -- Q-2026-10-07-39), recorded as every confirmed Refund draft (refunds.create, processed by
        -- the approver), after the Credit's latest event.
        FOR v_source IN SELECT value FROM jsonb_array_elements(v_paid) LOOP
            v_credit:=(v_source->>'customer_credit_id')::uuid;
            v_released:=(v_source->>'released_usd_cents')::bigint;
            SELECT credit.customer_id INTO STRICT v_recipient FROM app.customer_credits credit
            WHERE credit.id=v_credit;
            v_refund_id:=gen_random_uuid();
            v_at:=GREATEST(clock_timestamp(),app.credit_latest_at(v_credit)+interval '1 microsecond');
            PERFORM app.link_settlement_correction_effect(v_correction,'refund_id',v_refund_id);
            INSERT INTO app.settlement_correction_refund_details(refund_id,settlement_correction_id,
                draft_id,refund_method_id,reference_note,recorded_at)
            VALUES(v_refund_id,v_correction,p_draft,v_method,v_refund->>'reference_note',v_at);
            INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_payment_id,
                source_customer_credit_id,usd_accounting_value_cents,refund_currency,refund_amount_minor,
                reason,processed_at,processed_by,authorization_reference)
            VALUES(v_refund_id,'REF-' || v_refund_id::text,v_recipient,NULL,v_credit,v_released,'USD',
                v_released,v_draft.reason,v_at,p_actor,'refunds.create');
            v_refunds:=v_refunds||jsonb_build_array(jsonb_build_object('refund_id',v_refund_id,
                'customer_credit_id',v_credit,'recipient_customer_id',v_recipient,
                'amount_usd_cents',v_released));
        END LOOP;
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function, as the existing Invoice writers run them (sub-slice 10b plan note).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_after:=app.invoice_resource_snapshot(v_invoice.id);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
            entity_id,reason,authorization_reference,property_id,previous_state,resulting_state,
            correlation_id,source,outcome,authorization_evidence,linked_source_event_id,customer_id,
            lease_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'invoice.adjusted','invoice',
            v_invoice.id,v_draft.reason,'financial.approve',p_property,v_before,v_after,v_correction,
            'API','SUCCEEDED',v_evidence || jsonb_build_object('source_reference',v_reference,
                'invoice_line_id',v_line),
            v_adjustment,v_invoice.customer_id,v_invoice.lease_id);
        v_result:=app.settlement_refund_result(p_draft);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'final_settlement.correction.confirmed',
            'settlement_correction',v_correction,v_draft.reason,'financial.approve',p_property,
            '{{}}'::jsonb,
            jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,'variant','REFUND',
                'invoice_adjustment_id',v_adjustment,'invoice_id',v_invoice.id,'invoice_line_id',v_line,
                'customer_id',v_invoice.customer_id,'amount_usd_cents',v_amount,
                'refund_method_id',v_method,'refunds',v_refunds,
                -- Every reversal, re-post and released Credit the generic audits record without
                -- the correction is named here (design note point 2; review round 1).
                'released_sources',v_result->'released_sources'),
            v_correction,'API','SUCCEEDED',v_evidence,v_invoice.customer_id,v_invoice.lease_id,v_unit);
        RETURN v_result;
    END $$;
"""


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
            raise RuntimeError(f"Settlement Refund source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(SETTLEMENT_REFUND_SQL)
    _patch(GENERAL_SOURCE, GENERAL_SOURCE_REPLACEMENTS)
    _patch(CREDIT_CUSTOMER_CONFIRMED, CREDIT_CUSTOMER_CONFIRMED_REPLACEMENTS)
    op.execute(
        "REVOKE ALL ON TABLE app.settlement_correction_refund_details "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for function in (RECORD, CONFIRM, *INTERNAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD}, {CONFIRM} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Settlement Refund correction migration is forward-only")
