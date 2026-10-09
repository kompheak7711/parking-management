# ruff: noqa: E501
"""Post-settlement correction: REFUND of a paid Late-payment Charge (V1-056 sub-slice 10c-3b-1).

BR-SETTLE-013, BR-LATE-005, BR-CREDIT-006, BR-CREDIT-008, BR-CREDIT-014, BR-REFUND-014, DL-032,
BR-AUTH-010; owner answers to Q-2026-10-07-38 (b), Q-2026-10-07-41 answer 2, Q-2026-10-07-42 answers
1 and 2, Q-2026-10-09-66 and answer 4 to Q-2026-10-09-65:

- After the Lease's Final Settlement is closed, a wrong Late-payment Charge that was paid by Payment
  allocations or Credit applications is fixed by a REFUND correction: Staff record it under
  final_settlements.prepare with a reason, the Charge, the amount, a Refund method and a reference
  note; only a financial.approve holder confirms it.
- The confirm reverses, as linked records, what paid the reduced part (whole sources, newest
  first), writes one linked Late-payment Charge correction (REDUCTION, or CHARGE_REVERSAL for the
  whole current obligation), re-posts each source's unreleased rest to the same Charge, makes
  released Payment value Credit of the Charge's Customer (BR-CREDIT-014) and gives released Credit
  value back to its Credit, runs the shared DL-032 step (released Credit first pays its own
  Customer's open debt on the Lease) and refunds the rest to each Credit's Customer.
- A Charge a Deposit application paid is refused until sub-slice 10c-3b-2.

The release record `app.invoice_credit_excess_releases` is relaxed, never rebuilt: its Adjustment
link becomes optional and it gains an optional link to the Late-payment Charge correction, exactly
one of the two (owner answer 2 to Q-2026-10-09-66). New functions beside the Invoice-line ones
(migration 20261104_100); the Invoice-line REFUND confirm is patched so that it never takes a
Late-payment Charge draft, and the new confirm never takes an Invoice-line draft.
"""

from alembic import op
from sqlalchemy import text

revision = "20261117_113"
down_revision = "20261116_112"
branch_labels = None
depends_on = None

CHARGE_REASON = "Late-payment Charge correction credit excess"

# The release record (owner answer 2 to Q-2026-10-09-66): every existing row keeps its Adjustment and
# the old reason, so every check below holds for it.
RELEASE_TABLE = f"""
    ALTER TABLE app.invoice_credit_excess_releases ALTER COLUMN invoice_adjustment_id DROP NOT NULL;
    -- Explicit names: PostgreSQL would shorten the default ones (63 characters).
    ALTER TABLE app.invoice_credit_excess_releases ADD COLUMN late_payment_charge_correction_id uuid
        CONSTRAINT invoice_credit_excess_release_charge_correction_fkey
        REFERENCES app.late_payment_charge_corrections(id) ON DELETE RESTRICT;
    CREATE INDEX invoice_credit_excess_release_charge_correction_idx
        ON app.invoice_credit_excess_releases(late_payment_charge_correction_id);
    ALTER TABLE app.invoice_credit_excess_releases ADD CONSTRAINT invoice_credit_excess_release_one_link
        CHECK (num_nonnulls(invoice_adjustment_id,late_payment_charge_correction_id)=1);
    ALTER TABLE app.invoice_credit_excess_releases DROP CONSTRAINT invoice_credit_excess_releases_reason_check;
    ALTER TABLE app.invoice_credit_excess_releases ADD CONSTRAINT invoice_credit_excess_releases_reason_check
        CHECK ((invoice_adjustment_id IS NOT NULL AND reason='Invoice adjustment credit excess')
            OR (late_payment_charge_correction_id IS NOT NULL AND reason='{CHARGE_REASON}'));
"""

LINE_CONFIRM = "app.confirm_settlement_refund(uuid,uuid,uuid,text)"
LINE_CONFIRM_REPLACEMENTS = (
    (
        "              AND draft.payload->>'variant'='REFUND' AND decision.decision='CONFIRMED'\n",
        "              AND draft.payload->>'variant'='REFUND' AND decision.decision='CONFIRMED'\n"
        "              -- Sub-slice 10c-3b-1: a Late-payment Charge Refund has its own confirm.\n"
        "              AND draft.payload->'target_kind' IS NULL\n",
    ),
    (
        "            OR v_draft.payload->>'variant' IS DISTINCT FROM 'REFUND'\n",
        "            OR v_draft.payload->>'variant' IS DISTINCT FROM 'REFUND'\n"
        "            OR v_draft.payload->'target_kind' IS NOT NULL\n",
    ),
)

PLAN_LOCK = "app.lock_settlement_correction_plan(uuid)"
PLAN_LOCK_REPLACEMENTS = (
    (
        "        WHERE step->>'kind'<>'DEPOSIT_REFUNDS' AND step->>'target_kind'='LATE_PAYMENT_CHARGE';\n",
        "        WHERE step->>'kind'<>'DEPOSIT_REFUNDS' AND step->>'target_kind'='LATE_PAYMENT_CHARGE';\n"
        "        -- Sub-slice 10c-3b-1: a Late-payment Charge REFUND correction's Charge is locked FOR\n"
        "        -- UPDATE in the Charge pass; its source Invoice joins the Invoice pass through the\n"
        "        -- refund object, and its released sources' Payments and Credits the passes above.\n"
        "        IF v_draft.payload->>'variant'='REFUND' AND v_draft.payload->>'target_kind'='LATE_PAYMENT_CHARGE' THEN\n"
        "            v_target_charges:=v_target_charges\n"
        "                ||ARRAY[app.final_settlement_plan_id(v_draft.payload->'refund'->'late_payment_charge_id')::uuid];\n"
        "        END IF;\n",
    ),
)

RELEASE_VALIDATOR = "app.validate_invoice_credit_excess_release()"
RELEASE_VALIDATOR_REPLACEMENTS = (
    (
        "            IF NEW.source_kind='PAYMENT_ALLOCATION' THEN\n",
        "            -- Sub-slice 10c-3b-1: a release by a Late-payment Charge correction; the reversed\n"
        "            -- allocation or Credit application targets that Charge, carries the same reason, and\n"
        "            -- the release is at most what it applied.\n"
        "            IF NEW.late_payment_charge_correction_id IS NOT NULL THEN\n"
        "                IF NEW.source_kind='PAYMENT_ALLOCATION' THEN\n"
        "                    SELECT allocation.amount_usd_cents INTO v_on_line\n"
        "                    FROM app.late_payment_charge_corrections correction\n"
        "                    JOIN app.payment_allocations allocation\n"
        "                        ON allocation.late_payment_charge_id=correction.late_payment_charge_id\n"
        "                    JOIN app.payment_allocation_reversals reversal ON reversal.payment_allocation_id=allocation.id\n"
        "                    WHERE correction.id=NEW.late_payment_charge_correction_id\n"
        "                      AND correction.correction_kind IN ('REDUCTION','CHARGE_REVERSAL')\n"
        "                      AND allocation.id=NEW.reversed_payment_allocation_id AND reversal.reason=NEW.reason;\n"
        "                ELSE\n"
        "                    SELECT application.amount_usd_cents INTO v_on_line\n"
        "                    FROM app.late_payment_charge_corrections correction\n"
        "                    JOIN app.customer_credit_applications application\n"
        "                        ON application.late_payment_charge_id=correction.late_payment_charge_id\n"
        "                    JOIN app.customer_credit_application_reversals reversal\n"
        "                        ON reversal.credit_application_id=application.id\n"
        "                    WHERE correction.id=NEW.late_payment_charge_correction_id\n"
        "                      AND correction.correction_kind IN ('REDUCTION','CHARGE_REVERSAL')\n"
        "                      AND application.id=NEW.reversed_credit_application_id AND reversal.reason=NEW.reason;\n"
        "                END IF;\n"
        "                IF v_on_line IS NULL OR NEW.released_usd_cents>v_on_line THEN\n"
        "                    RAISE EXCEPTION 'Credit excess release does not match its reversed source'\n"
        "                        USING ERRCODE='23514'; END IF;\n"
        "                RETURN NEW;\n"
        "            END IF;\n"
        "            IF NEW.source_kind='PAYMENT_ALLOCATION' THEN\n",
    ),
)

CREDIT_RECOGNITION = "app.validate_credit_recognition()"
CREDIT_RECOGNITION_REPLACEMENTS = (
    (
        "            IF v_adjustment_customer IS NULL THEN\n"
        "                PERFORM app.assert_payment_excess_eligible(v_payment.id);\n",
        "            -- Sub-slice 10c-3b-1: released Payment value of a Late-payment Charge correction\n"
        "            -- belongs to the Charge's Customer at once (BR-CREDIT-014).\n"
        "            IF v_adjustment_customer IS NULL THEN\n"
        "                SELECT charge.customer_id INTO v_adjustment_customer\n"
        "                FROM app.invoice_credit_excess_releases release\n"
        "                JOIN app.late_payment_charge_corrections correction\n"
        "                    ON correction.id=release.late_payment_charge_correction_id\n"
        "                JOIN app.late_payment_charges charge ON charge.id=correction.late_payment_charge_id\n"
        "                WHERE release.customer_credit_id=NEW.id\n"
        "                  AND release.released_usd_cents=NEW.recognized_usd_cents\n"
        "                  AND release.source_kind='PAYMENT_ALLOCATION';\n"
        "            END IF;\n"
        "            IF v_adjustment_customer IS NULL THEN\n"
        "                PERFORM app.assert_payment_excess_eligible(v_payment.id);\n",
    ),
)

REFUND_ALLOWED = "app.settlement_correction_refund_allowed(app.refunds)"
REFUND_ALLOWED_REPLACEMENTS = (
    (
        "                    JOIN app.invoice_credit_excess_releases release\n"
        "                        ON release.invoice_adjustment_id=effect.invoice_adjustment_id\n",
        "                    -- Sub-slice 10c-3b-1: or the correction's Late-payment Charge correction.\n"
        "                    JOIN app.invoice_credit_excess_releases release\n"
        "                        ON release.invoice_adjustment_id=effect.invoice_adjustment_id\n"
        "                        OR release.late_payment_charge_correction_id=effect.late_payment_charge_correction_id\n",
    ),
)

CREDIT_KEY = "app.settlement_correction_credit_id(uuid,uuid)"
CREDIT_KEY_REPLACEMENTS = (
    (
        "                JOIN app.invoice_credit_excess_releases release\n"
        "                    ON release.invoice_adjustment_id=effect.invoice_adjustment_id\n",
        "                -- Sub-slice 10c-3b-1: or the correction's Late-payment Charge correction.\n"
        "                JOIN app.invoice_credit_excess_releases release\n"
        "                    ON release.invoice_adjustment_id=effect.invoice_adjustment_id\n"
        "                    OR release.late_payment_charge_correction_id=effect.late_payment_charge_correction_id\n",
    ),
)

ALLOCATION_AUDIT = "app.audit_payment_allocation_event()"
ALLOCATION_AUDIT_REPLACEMENTS = (
    (
        "                    THEN 'Invoice adjustment credit excess'\n",
        "                    -- Sub-slice 10c-3b-1: the release row's reason.\n"
        "                    THEN (SELECT release.reason FROM app.invoice_credit_excess_releases release\n"
        "                        WHERE release.replacement_payment_allocation_id=NEW.id)\n",
    ),
)

APPLICATION_AUDIT = "app.audit_credit_application_event()"
APPLICATION_AUDIT_REPLACEMENTS = (
    (
        "                    THEN 'Invoice adjustment credit excess' ELSE 'Confirmed Credit application' END;\n",
        "                    -- Sub-slice 10c-3b-1: the release row's reason.\n"
        "                    THEN (SELECT release.reason FROM app.invoice_credit_excess_releases release\n"
        "                        WHERE release.replacement_credit_application_id=NEW.id)\n"
        "                    ELSE 'Confirmed Credit application' END;\n",
    ),
)

# Owner approval of 2026-10-09 (in session, Q-2026-10-09-68): the overlay's released Payment value
# may come from an allocation on a Late-payment Charge of this Lease, Credit of the Charge's Customer.
PLAN_CHECK = "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)"
PLAN_CHECK_REPLACEMENTS = (
    (
        "                    SELECT 1 FROM app.payment_allocations allocation\n"
        "                    JOIN app.invoices invoice ON invoice.id=allocation.invoice_id\n"
        "                    WHERE allocation.id=v_entry.key::uuid AND invoice.lease_id=v_lease\n"
        "                      AND invoice.customer_id=v_customer)\n",
        "                    SELECT 1 FROM app.payment_allocations allocation\n"
        "                    -- Sub-slice 10c-3b-1: or an allocation on a Late-payment Charge of this\n"
        "                    -- Lease, released as Credit of the Charge's Customer (BR-CREDIT-014).\n"
        "                    LEFT JOIN app.late_payment_charges charge ON charge.id=allocation.late_payment_charge_id\n"
        "                    JOIN app.invoices invoice ON invoice.id=COALESCE(allocation.invoice_id,charge.source_invoice_id)\n"
        "                    WHERE allocation.id=v_entry.key::uuid AND invoice.lease_id=v_lease\n"
        "                      AND COALESCE(charge.customer_id,invoice.customer_id)=v_customer)\n",
    ),
)

PATCHES = (
    (LINE_CONFIRM, LINE_CONFIRM_REPLACEMENTS),
    (PLAN_LOCK, PLAN_LOCK_REPLACEMENTS),
    (RELEASE_VALIDATOR, RELEASE_VALIDATOR_REPLACEMENTS),
    (CREDIT_RECOGNITION, CREDIT_RECOGNITION_REPLACEMENTS),
    (REFUND_ALLOWED, REFUND_ALLOWED_REPLACEMENTS),
    (CREDIT_KEY, CREDIT_KEY_REPLACEMENTS),
    (ALLOCATION_AUDIT, ALLOCATION_AUDIT_REPLACEMENTS),
    (APPLICATION_AUDIT, APPLICATION_AUDIT_REPLACEMENTS),
    (PLAN_CHECK, PLAN_CHECK_REPLACEMENTS),
)

SQL = r"""
    -- The draft's Late-payment Charge Refund, checked for shape only and stored in one form (the
    -- plan is checked by the recorder): malformed input 22023.
    CREATE FUNCTION app.settlement_late_charge_refund_input(p_refund jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_charge text; v_method text;
    BEGIN
        IF p_refund IS NULL OR jsonb_typeof(p_refund) IS DISTINCT FROM 'object'
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_refund) key
                WHERE key NOT IN ('late_payment_charge_id','amount_usd_cents','refund_method_id',
                    'reference_note','plan'))
        THEN RAISE EXCEPTION 'Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        v_charge:=app.final_settlement_plan_id(p_refund->'late_payment_charge_id');
        v_method:=app.final_settlement_plan_id(p_refund->'refund_method_id');
        IF v_charge IS NULL OR v_method IS NULL
            OR jsonb_typeof(p_refund->'amount_usd_cents') IS DISTINCT FROM 'number'
            OR (p_refund->>'amount_usd_cents') !~ '^[1-9][0-9]{0,15}$'
            OR jsonb_typeof(p_refund->'reference_note') IS DISTINCT FROM 'string'
            OR app.lease_notice_text_valid(p_refund->>'reference_note',500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        -- The cap of the other money writers; a JSON number always casts.
        IF (p_refund->>'amount_usd_cents')::numeric>9000000000000000 THEN
            RAISE EXCEPTION 'Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        RETURN jsonb_build_object('late_payment_charge_id',v_charge,
            'amount_usd_cents',(p_refund->>'amount_usd_cents')::bigint,'refund_method_id',v_method,
            'reference_note',p_refund->>'reference_note');
    END $$;

    -- What pays a Late-payment Charge now, newest first (migration 67, Q-41 answer 2): every Payment
    -- allocation, Credit application and Deposit application on it that is not reversed, whole.
    -- Released Payment value belongs to the Charge's Customer (BR-CREDIT-014), released Credit value
    -- to its own Credit's Customer (BR-CREDIT-008).
    CREATE FUNCTION app.settlement_late_charge_refund_sources(p_charge uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT COALESCE(jsonb_agg(jsonb_build_object('kind',source.kind,'id',source.id,
                'on_charge_usd_cents',source.on_charge,'at',source.at,'payment_id',source.payment_id,
                'credit_id',source.credit_id,'recipient_customer_id',source.recipient,
                'payer_customer_id',payment.payer_customer_id)
                || CASE WHEN source.kind='DEPOSIT_APPLICATION'
                    THEN jsonb_build_object('deposit_id',source.deposit_id) ELSE '{}'::jsonb END
            ORDER BY source.at DESC,source.id DESC),'[]'::jsonb)
        FROM (
            SELECT 'PAYMENT_ALLOCATION'::text AS kind,allocation.id,allocation.amount_usd_cents AS on_charge,
                allocation.posted_at AS at,allocation.payment_id,NULL::uuid AS credit_id,
                charge.customer_id AS recipient,NULL::uuid AS deposit_id
            FROM app.payment_allocations allocation
            JOIN app.late_payment_charges charge ON charge.id=allocation.late_payment_charge_id
            WHERE allocation.late_payment_charge_id=p_charge
              AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                  WHERE reversal.payment_allocation_id=allocation.id)
            UNION ALL
            SELECT 'CREDIT_APPLICATION',application.id,application.amount_usd_cents,
                application.occurred_at,credit.source_payment_id,credit.id,credit.customer_id,NULL::uuid
            FROM app.customer_credit_applications application
            JOIN app.customer_credits credit ON credit.id=application.customer_credit_id
            WHERE application.late_payment_charge_id=p_charge
              AND NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal
                  WHERE reversal.credit_application_id=application.id)
            UNION ALL
            SELECT 'DEPOSIT_APPLICATION',application.id,application.amount_usd_cents,
                application.occurred_at,NULL::uuid,NULL::uuid,deposit.customer_id,application.deposit_id
            FROM app.deposit_applications application
            JOIN app.deposits deposit ON deposit.id=application.deposit_id
            WHERE application.late_payment_charge_id=p_charge
              AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
                  WHERE reversal.deposit_application_id=application.id)
        ) source
        LEFT JOIN app.payments payment ON payment.id=source.payment_id
    $$;

    -- The state a Late-payment Charge Refund depends on; its digest is the draft's source revision:
    -- the Settlement, the Charge (current obligation, corrections, active applications, VOID state)
    -- and every source that pays it with its Credit.
    CREATE FUNCTION app.settlement_late_charge_refund_source_state(p_settlement uuid,p_charge uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        SELECT app.settlement_late_charge_reduction_source_state(p_settlement,p_charge)
            || jsonb_build_object('sources',app.settlement_late_charge_refund_sources(p_charge))
    $$;

    -- The shared step's overlay after the release: the Charge's corrected rest as its obligation
    -- (what a reversed Deposit application leaves unpaid; none until sub-slice 10c-3b-2), released
    -- Deposit value back in its Deposit, and the released Credit (released Payment value keyed by
    -- its allocation and given to the Charge's Customer, released Credit value back to its Credit).
    CREATE FUNCTION app.settlement_late_charge_refund_overlay(p_released jsonb,p_charge uuid)
    RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
        SELECT jsonb_build_object(
            'obligations',jsonb_build_object('LATE_PAYMENT_CHARGE:' || p_charge::text,
                COALESCE((SELECT sum((source->>'application_usd_cents')::bigint-(source->>'released_usd_cents')::bigint)
                    FROM jsonb_array_elements(p_released) source
                    WHERE source->>'kind'='DEPOSIT_APPLICATION'),0)),
            'deposits',COALESCE((SELECT jsonb_object_agg(deposit.id,deposit.total) FROM (
                    SELECT source->>'deposit_id' AS id,sum((source->>'application_usd_cents')::bigint) AS total
                    FROM jsonb_array_elements(p_released) source
                    WHERE source->>'kind'='DEPOSIT_APPLICATION' GROUP BY 1) deposit),'{}'::jsonb),
            'credits',COALESCE((SELECT jsonb_object_agg(credit.key,jsonb_build_object(
                    'customer_id',credit.customer,'add_usd_cents',credit.total,
                    'released_payment_allocation_id',credit.allocation)) FROM (
                    SELECT CASE WHEN source->>'kind'='PAYMENT_ALLOCATION' THEN source->>'id'
                            ELSE source->>'credit_id' END AS key,
                        min(source->>'recipient_customer_id') AS customer,
                        sum((source->>'released_usd_cents')::bigint) AS total,
                        min(CASE WHEN source->>'kind'='PAYMENT_ALLOCATION' THEN source->>'id' END) AS allocation
                    FROM jsonb_array_elements(p_released) source
                    WHERE source->>'kind' IN ('PAYMENT_ALLOCATION','CREDIT_APPLICATION') GROUP BY 1) credit),
                '{}'::jsonb))
    $$;

    -- Checks a stored-form Refund against the current state and returns what the draft records: the
    -- Lease, the Charge's Customer, the Refund with the Charge's source Invoice, the sources it
    -- releases and the source revision. An unknown Settlement or a Charge not of its Lease P0002; a
    -- state the correction does not allow 55000.
    CREATE FUNCTION app.settlement_late_charge_refund_plan(p_property uuid,p_settlement uuid,p_refund jsonb)
    RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_settlement app.final_settlements%ROWTYPE; v_charge app.late_payment_charges%ROWTYPE;
        v_invoice app.invoices%ROWTYPE; v_summary jsonb; v_amount bigint; v_current bigint;
        v_remaining bigint; v_release bigint; v_source jsonb; v_released jsonb:='[]'::jsonb;
    BEGIN
        SELECT * INTO v_settlement FROM app.final_settlements
        WHERE id=p_settlement AND property_id=p_property;
        IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
        IF v_settlement.closed_at IS NULL THEN
            RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                USING ERRCODE='55000'; END IF;
        SELECT charge.* INTO v_charge FROM app.late_payment_charges charge
        JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
        WHERE charge.id=(p_refund->>'late_payment_charge_id')::uuid
          AND invoice.lease_id=v_settlement.lease_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The corrected Late-payment Charge is not a Charge of this Final Settlement'
                USING ERRCODE='P0002'; END IF;
        SELECT * INTO STRICT v_invoice FROM app.invoices WHERE id=v_charge.source_invoice_id;
        IF v_invoice.status='VOID' OR EXISTS(SELECT 1 FROM app.late_payment_charge_corrections correction
            WHERE correction.late_payment_charge_id=v_charge.id AND correction.correction_kind='CHARGE_REVERSAL')
        THEN RAISE EXCEPTION 'The corrected Late-payment Charge is not an open obligation of this Final Settlement'
            USING ERRCODE='55000'; END IF;
        v_summary:=app.late_payment_charge_application_summary(v_charge.id);
        -- 8a-1: a Charge that a Deposit application paid takes no correction until sub-slice 10c-3b-2.
        IF (v_summary->>'deposit_total_usd_cents')::bigint>0 THEN
            RAISE EXCEPTION 'A Deposit application paid this obligation at Final Settlement'
                USING ERRCODE='55000'; END IF;
        v_amount:=(p_refund->>'amount_usd_cents')::bigint;
        v_current:=app.settlement_late_charge_obligation(v_charge.id);
        IF v_amount>v_current THEN
            RAISE EXCEPTION 'The Refund correction exceeds the Late-payment Charge' USING ERRCODE='55000'; END IF;
        -- Design note: a REFUND always releases paid value; removing only unpaid value is a reduction.
        v_remaining:=v_amount-(v_current-(v_summary->>'active_total_usd_cents')::bigint);
        IF v_remaining<=0 THEN
            RAISE EXCEPTION 'The Refund correction releases no paid value; an unpaid charge is removed by a charge reduction'
                USING ERRCODE='55000'; END IF;
        -- BR-REFUND-014: an active Refund method (as the Final Settlement draft).
        PERFORM 1 FROM app.refund_methods WHERE id=(p_refund->>'refund_method_id')::uuid AND active;
        IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
        -- Whole sources, newest first, until the paid part is covered (migration 67, Q-41 answer 2).
        FOR v_source IN SELECT value FROM jsonb_array_elements(app.settlement_late_charge_refund_sources(v_charge.id))
        LOOP
            EXIT WHEN v_remaining<=0;
            v_release:=LEAST((v_source->>'on_charge_usd_cents')::bigint,v_remaining);
            v_released:=v_released||jsonb_build_array((v_source-'on_charge_usd_cents'-'at')
                ||jsonb_build_object('released_usd_cents',v_release));
            v_remaining:=v_remaining-v_release;
        END LOOP;
        IF v_remaining>0 THEN
            RAISE EXCEPTION 'Credit excess exceeds the applied value of the Late-payment Charge' USING ERRCODE='23514';
        END IF;
        RETURN jsonb_build_object('lease_id',v_settlement.lease_id,'customer_id',v_charge.customer_id,
            'refund',p_refund || jsonb_build_object('invoice_id',v_charge.source_invoice_id),
            'released_sources',v_released,
            'source_revision','settlement-correction:' || encode(sha256(convert_to(
                app.settlement_late_charge_refund_source_state(p_settlement,v_charge.id)::text,
                'UTF8')),'hex'));
    END $$;

    -- Staff record a Late-payment Charge Refund correction draft (final_settlements.prepare); it has
    -- no financial effect until a financial.approve holder confirms it.
    CREATE FUNCTION app.record_settlement_late_charge_refund_draft(p_property uuid,p_actor uuid,
        p_draft uuid,p_settlement uuid,p_refund jsonb,p_reason text,p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_existing app.financial_drafts%ROWTYPE; v_input jsonb; v_plan jsonb; v_payload jsonb;
        v_steps jsonb; v_overlay jsonb; v_result jsonb; v_choice text;
    BEGIN
        PERFORM app.require_invoice_command_actor(p_property,p_actor);
        PERFORM app.assert_active_financial_actor(p_actor,p_property);
        IF p_authorization IS DISTINCT FROM 'final_settlements.prepare' THEN
            RAISE EXCEPTION 'Post-settlement correction draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
        -- The reason is at most 500 characters: the Charge correction keeps it (as
        -- app.correct_late_payment_charge).
        IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_settlement IS NULL
            OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
        THEN RAISE EXCEPTION 'Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        v_input:=app.settlement_late_charge_refund_input(p_refund);
        -- The plan (the Settlement plan format); none means nothing is paid before the Refunds.
        v_steps:=COALESCE(p_refund->'plan',jsonb_build_object('steps','[]'::jsonb,'pet_remainder','null'::jsonb));
        IF jsonb_typeof(v_steps) IS DISTINCT FROM 'object' OR jsonb_typeof(v_steps->'steps') IS DISTINCT FROM 'array'
        THEN RAISE EXCEPTION 'Refund correction input is invalid' USING ERRCODE='22023'; END IF;
        -- An exact repeat replays before any current-state check.
        PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
        SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
        IF FOUND THEN
            IF v_existing.property_id=p_property AND v_existing.kind='SETTLEMENT_CORRECTION'
                AND v_existing.payload->>'variant'='REFUND'
                AND v_existing.payload->>'target_kind'='LATE_PAYMENT_CHARGE'
                AND v_existing.prepared_by=p_actor AND v_existing.reason=p_reason
                AND v_existing.payload->>'final_settlement_id'=p_settlement::text
                AND (v_existing.payload->'refund')-'invoice_id'=v_input AND v_existing.payload->'plan'=v_steps
            -- The decision's transaction id never leaves the database (sub-slice 10b).
            THEN RETURN app.financial_draft_json(v_existing) #- '{decision,result,transaction_id}'; END IF;
            RAISE EXCEPTION 'Post-settlement correction draft identity was reused' USING ERRCODE='P5205';
        END IF;
        v_plan:=app.settlement_late_charge_refund_plan(p_property,p_settlement,v_input);
        -- One Refund method and reference note per correction (owner answer 1 to the 10c-1b points):
        -- every Deposit Refund step uses the draft's.
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(v_steps->'steps') step
            WHERE step->>'kind'='DEPOSIT_REFUNDS'
              AND (app.final_settlement_plan_id(step->'refund_method_id') IS DISTINCT FROM v_input->>'refund_method_id'
                  OR step->'reference_note' IS DISTINCT FROM v_input->'reference_note'))
        THEN RAISE EXCEPTION 'A post-settlement correction has one Refund method, reference note, recipient and agreement'
            USING ERRCODE='22023'; END IF;
        -- Owner answer 3 to Q-2026-10-07-44: the remaining Pet Deposit is used by the Customer's
        -- choice given for this correction; neither the Final Settlement's choice nor that of an
        -- earlier confirmed correction is reused. The database compares the recorded text only.
        IF v_steps->'pet_remainder'->>'basis'='CUSTOMER_CHOICE' THEN
            SELECT draft.payload->'pet_remainder'->>'customer_choice' INTO v_choice
            FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision
                ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
            WHERE draft.kind='FINAL_SETTLEMENT' AND draft.payload->>'final_settlement_id'=p_settlement::text;
            IF v_choice IS NOT NULL AND v_choice=v_steps->'pet_remainder'->>'customer_choice' THEN
                RAISE EXCEPTION 'A correction needs the Customer''s choice for this correction; the Final Settlement''s choice is not reused'
                    USING ERRCODE='55000'; END IF;
            IF EXISTS(SELECT 1 FROM app.financial_drafts draft
                JOIN app.financial_draft_decisions decision
                    ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
                WHERE draft.kind='SETTLEMENT_CORRECTION'
                  AND draft.payload->>'final_settlement_id'=p_settlement::text
                  AND draft.payload->'plan'->'pet_remainder'->>'customer_choice'
                      =v_steps->'pet_remainder'->>'customer_choice')
            THEN RAISE EXCEPTION 'A correction needs the Customer''s choice for this correction; an earlier correction''s choice is not reused'
                USING ERRCODE='55000'; END IF;
        END IF;
        -- The shared step's check on the state after the release (sub-slice 10c-2a-2).
        v_overlay:=app.settlement_late_charge_refund_overlay(v_plan->'released_sources',
            (v_input->>'late_payment_charge_id')::uuid);
        v_result:=app.settlement_correction_plan_result(p_property,p_actor,p_settlement,v_steps,v_overlay)
            -'source_revision';
        v_payload:=jsonb_build_object('variant','REFUND','target_kind','LATE_PAYMENT_CHARGE',
            'final_settlement_id',p_settlement,'lease_id',v_plan->'lease_id',
            'customer_id',v_plan->'customer_id','refund',v_plan->'refund',
            'released_sources',v_plan->'released_sources',
            'plan',v_steps,'plan_overlay',v_overlay,'plan_result',v_result);
        RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'SETTLEMENT_CORRECTION',
            'final_settlements.prepare',v_payload,v_plan->>'source_revision',p_reason);
    END $$;

    -- What the confirm returns, also for an exact repeat (rebuilt from the stored records): the
    -- draft without the decision's transaction id, the correction header, the linked Charge
    -- correction, the released sources (from the release rows), the step's records, the Refunds and
    -- the Charge.
    CREATE FUNCTION app.settlement_late_charge_refund_result(p_draft uuid)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        WITH charge_correction AS (
            SELECT charge_correction.* FROM app.settlement_correction_effects effect
            JOIN app.late_payment_charge_corrections charge_correction
                ON charge_correction.id=effect.late_payment_charge_correction_id
            WHERE effect.settlement_correction_id=app.settlement_correction_id(p_draft))
        SELECT jsonb_build_object(
            'draft',app.financial_draft_json(draft) #- '{decision,result,transaction_id}',
            'settlement_correction',(SELECT jsonb_build_object('id',correction.id,
                    'final_settlement_id',correction.final_settlement_id,'reason',correction.reason,
                    'occurred_at',correction.occurred_at,'actor_id',correction.actor_id,
                    'authorization_reference',correction.authorization_reference)
                FROM app.settlement_corrections correction
                WHERE correction.id=app.settlement_correction_id(draft.id)),
            'late_payment_charge_correction',(SELECT jsonb_build_object('id',charge_correction.id,
                    'late_payment_charge_id',charge_correction.late_payment_charge_id,
                    'correction_kind',charge_correction.correction_kind,
                    'amount_usd_cents',charge_correction.amount_usd_cents,
                    'previous_obligation_usd_cents',charge_correction.previous_obligation_usd_cents,
                    'resulting_obligation_usd_cents',charge_correction.resulting_obligation_usd_cents,
                    'reason',charge_correction.reason,'occurred_at',charge_correction.occurred_at,
                    'actor_id',charge_correction.actor_id,
                    'authorization_reference',charge_correction.authorization_reference)
                FROM charge_correction),
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
                WHERE release.late_payment_charge_correction_id=(SELECT id FROM charge_correction)),
            'deposit_application_reversals',(SELECT COALESCE(jsonb_agg(jsonb_build_object(
                    'id',reversal.id,'deposit_application_id',reversal.deposit_application_id,
                    'deposit_id',application.deposit_id,'amount_usd_cents',application.amount_usd_cents,
                    'occurred_at',reversal.occurred_at) ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.deposit_application_reversals reversal ON reversal.id=effect.deposit_application_reversal_id
                JOIN app.deposit_applications application ON application.id=reversal.deposit_application_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)),
            'credit_applications',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',application.id,
                    'customer_credit_id',application.customer_credit_id,'target_kind',application.target_kind,
                    'invoice_id',application.invoice_id,'late_payment_charge_id',application.late_payment_charge_id,
                    'amount_usd_cents',application.amount_usd_cents,
                    'within_invoice_basis',application.within_invoice_basis) ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.customer_credit_applications application ON application.id=effect.customer_credit_application_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)
                  AND application.final_settlement_id IS NOT NULL),
            'deposit_applications',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',application.id,
                    'deposit_id',application.deposit_id,'application_stage',application.application_stage,
                    'target_kind',application.target_kind,'invoice_line_id',application.invoice_line_id,
                    'late_payment_charge_id',application.late_payment_charge_id,
                    'amount_usd_cents',application.amount_usd_cents,
                    'application_order',application.application_order) ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.deposit_applications application ON application.id=effect.deposit_application_id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)),
            'refunds',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',refund.id,
                    'refund_number',refund.refund_number,
                    'recipient_customer_id',refund.recipient_customer_id,
                    'source_customer_credit_id',refund.source_customer_credit_id,
                    'source_deposit_id',refund.source_deposit_id,
                    'amount_usd_cents',refund.usd_accounting_value_cents,
                    'refund_method_id',detail.refund_method_id,'reference_note',detail.reference_note,
                    'signer_agreement',detail.signer_agreement,
                    'reason',refund.reason,'processed_at',refund.processed_at,
                    'processed_by',refund.processed_by,
                    'authorization_reference',refund.authorization_reference)
                    ORDER BY effect.effect_sequence),'[]'::jsonb)
                FROM app.settlement_correction_effects effect
                JOIN app.refunds refund ON refund.id=effect.refund_id
                JOIN app.settlement_correction_refund_details detail ON detail.refund_id=refund.id
                WHERE effect.settlement_correction_id=app.settlement_correction_id(draft.id)),
            'late_payment_charge',app.late_payment_charge_snapshot((SELECT late_payment_charge_id
                FROM charge_correction)))
        FROM app.financial_drafts draft WHERE draft.id=p_draft
    $$;

    -- The time of a record on a Late-payment Charge written by this correction: after the Charge's
    -- latest event (allocations, Credit and Deposit applications, their reversals and corrections)
    -- and, for a Credit's record, after the Credit's latest event. VOLATILE: it reads the clock.
    CREATE FUNCTION app.settlement_late_charge_instant(p_charge uuid,p_credit uuid)
    RETURNS timestamptz LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT GREATEST(clock_timestamp(),
            COALESCE(app.allocation_target_latest_at('LATE_PAYMENT_CHARGE',p_charge),'-infinity')
                +interval '1 microsecond',
            COALESCE((SELECT app.credit_latest_at(p_credit) WHERE p_credit IS NOT NULL),'-infinity')
                +interval '1 microsecond')
    $$;

    -- A financial.approve holder confirms a Late-payment Charge Refund correction. Refusals: an
    -- unknown Property, draft or Settlement P0002/P4501; an inactive or missing approver P4506 or
    -- 42501; business state (a decided draft, an open Settlement, an inactive Refund method) 55000;
    -- a draft whose sources changed since it was recorded P5S02 (stale; it stays pending). Nothing
    -- is written unless everything succeeds.
    CREATE FUNCTION app.confirm_settlement_late_charge_refund(p_property uuid,p_actor uuid,p_draft uuid,
        p_authorization text)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
        v_charge app.late_payment_charges%ROWTYPE; v_timezone text; v_now timestamptz;
        v_business_date date; v_refund jsonb; v_plan jsonb; v_correction uuid; v_row uuid;
        v_amount bigint; v_current bigint; v_kind text; v_method uuid; v_lease uuid; v_unit uuid;
        v_before jsonb; v_after jsonb; v_evidence jsonb; v_result jsonb; v_source jsonb;
        v_released bigint; v_new uuid; v_credit uuid; v_recipient uuid; v_at timestamptz;
        v_rest bigint; v_refund_id uuid; v_step jsonb; v_left jsonb:='{}'::jsonb; v_pay bigint;
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
              AND draft.payload->>'variant'='REFUND'
              AND draft.payload->>'target_kind'='LATE_PAYMENT_CHARGE' AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor)
        THEN RETURN app.settlement_late_charge_refund_result(p_draft); END IF;
        SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
        IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION'
            OR v_draft.prepare_capability<>'final_settlements.prepare'
            OR v_draft.payload->>'variant' IS DISTINCT FROM 'REFUND'
            OR v_draft.payload->>'target_kind' IS DISTINCT FROM 'LATE_PAYMENT_CHARGE'
            OR jsonb_typeof(v_draft.payload->'refund') IS DISTINCT FROM 'object'
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
        -- The stored Refund (without the source Invoice the plan added) passes the recorder's shape
        -- check again.
        v_refund:=app.settlement_late_charge_refund_input((v_draft.payload->'refund')-'invoice_id');
        IF v_refund IS DISTINCT FROM (v_draft.payload->'refund')-'invoice_id' THEN
            RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
        v_amount:=(v_refund->>'amount_usd_cents')::bigint;
        v_method:=(v_refund->>'refund_method_id')::uuid;
        -- Lock order, the 8e-3 order (as the Invoice-line REFUND confirm): the draft lock (above);
        -- the Settlement's draft lock; the Lease row FOR UPDATE; then the shared step's locks
        -- (app.lock_settlement_correction_plan), which for this draft take the Payments of the
        -- released sources and of the Credit steps, then their Credits, each in one id-ordered pass;
        -- the Lease's Charges in id order with this Charge FOR UPDATE; the Lease's Invoices in id
        -- order with the Charge's source Invoice FOR UPDATE (no Invoice before a Charge, as a
        -- one-call writer locks a Charge and then its source Invoice); the Settlement row; and each
        -- Deposit's draft lock and row. A source added after the draft is not locked here, but it
        -- changes the source revision, so the draft is stale below.
        PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
        PERFORM 1 FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE;
        PERFORM app.lock_settlement_correction_plan(p_draft);
        SELECT * INTO v_charge FROM app.late_payment_charges
        WHERE id=(v_refund->>'late_payment_charge_id')::uuid FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The corrected Late-payment Charge is not a Charge of this Final Settlement'
                USING ERRCODE='P0002'; END IF;
        PERFORM 1 FROM app.invoices WHERE id=v_charge.source_invoice_id FOR UPDATE;
        -- Under the locks, the sources still have the digest the draft recorded, and the check of
        -- the recorder still gives the same release; otherwise the draft is stale and stays pending.
        IF 'settlement-correction:' || encode(sha256(convert_to(app.settlement_late_charge_refund_source_state(
                v_settlement.id,v_charge.id)::text,'UTF8')),'hex')
            IS DISTINCT FROM v_draft.source_revision
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        v_plan:=app.settlement_late_charge_refund_plan(p_property,v_settlement.id,v_refund);
        IF v_plan->>'source_revision' IS DISTINCT FROM v_draft.source_revision
            OR v_plan->'lease_id' IS DISTINCT FROM v_draft.payload->'lease_id'
            OR v_plan->'customer_id' IS DISTINCT FROM v_draft.payload->'customer_id'
            OR v_plan->'refund' IS DISTINCT FROM v_draft.payload->'refund'
            OR v_plan->'released_sources' IS DISTINCT FROM v_draft.payload->'released_sources'
        THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'
            USING ERRCODE='P5S02'; END IF;
        -- BR-REFUND-014: the method stays active until the Refunds are written (as sub-slice 8d).
        PERFORM 1 FROM app.refund_methods WHERE id=v_method AND active FOR SHARE;
        IF NOT FOUND THEN RAISE EXCEPTION 'Refund Method is not active' USING ERRCODE='55000'; END IF;
        SELECT invoice.lease_id,lease.unit_id INTO STRICT v_lease,v_unit FROM app.invoices invoice
        JOIN app.leases lease ON lease.id=invoice.lease_id WHERE invoice.id=v_charge.source_invoice_id;
        v_current:=app.settlement_late_charge_obligation(v_charge.id);
        -- BR-LATE-005 and the Charge correction row's rules: removing the whole current obligation
        -- is the Charge reversal (terminal); any smaller amount is a reduction.
        v_kind:=CASE WHEN v_amount=v_current THEN 'CHARGE_REVERSAL' ELSE 'REDUCTION' END;

        -- The decision, then the header (sub-slice 10a). From here every record is linked before
        -- it is written, and every id is fresh, never derived from the draft (sub-slice 10b).
        v_correction:=app.begin_settlement_correction(p_property,p_actor,p_draft,'financial.approve');
        v_before:=app.late_payment_charge_snapshot(v_charge.id);
        v_evidence:=jsonb_build_object('capability','financial.approve','draft_id',p_draft,
            'settlement_correction_id',v_correction,'final_settlement_id',v_settlement.id,
            'variant','REFUND','target_kind','LATE_PAYMENT_CHARGE');
        -- Phase 1: reverse each released source whole, newest first (migration 67; Q-41 answer 2),
        -- each dated after the Charge's latest event and, for a Credit application, its Credit's.
        -- A Settlement Credit application's reversal passes the 8e-2 refusal because it is linked
        -- first. (A Deposit application is never a source until sub-slice 10c-3b-2: the plan refuses
        -- a Deposit-paid Charge.)
        FOR v_source IN SELECT value FROM jsonb_array_elements(v_plan->'released_sources') LOOP
            v_new:=gen_random_uuid();
            IF v_source->>'kind'='PAYMENT_ALLOCATION' THEN
                PERFORM app.link_settlement_correction_effect(v_correction,
                    'payment_allocation_reversal_id',v_new);
                INSERT INTO app.payment_allocation_reversals(id,payment_allocation_id,reason,
                    occurred_at,actor_id,authorization_reference)
                VALUES(v_new,(v_source->>'id')::uuid,'Late-payment Charge correction credit excess',
                    app.settlement_late_charge_instant(v_charge.id,NULL),p_actor,'payments.allocations.reverse');
            ELSE
                PERFORM app.link_settlement_correction_effect(v_correction,
                    'credit_application_reversal_id',v_new);
                INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,reason,
                    occurred_at,actor_id,authorization_reference)
                VALUES(v_new,(v_source->>'id')::uuid,'Late-payment Charge correction credit excess',
                    app.settlement_late_charge_instant(v_charge.id,(v_source->>'credit_id')::uuid),p_actor,
                    'credits.applications.reverse');
            END IF;
        END LOOP;
        -- The Charge correction after the reversals, stamped after every allocation, Credit
        -- application, reversal and correction on the Charge (its serializer; 10c-3a security note
        -- 3). It passes the 8e-1 refusal only because it is linked to this correction first. Its
        -- deferred validator (no result below the active applications) runs at the end, when the
        -- re-posted rests below are written.
        v_now:=app.settlement_late_charge_instant(v_charge.id,NULL);
        v_business_date:=timezone(v_timezone,v_now)::date;
        v_row:=gen_random_uuid();
        PERFORM app.link_settlement_correction_effect(v_correction,'late_payment_charge_correction_id',v_row);
        INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,correction_kind,
            amount_usd_cents,reverses_correction_id,reason,previous_obligation_usd_cents,
            resulting_obligation_usd_cents,occurred_at,actor_id,authorization_reference,correlation_id)
        VALUES (v_row,v_charge.id,v_kind,v_amount,NULL,v_draft.reason,v_current,v_current-v_amount,
            v_now,p_actor,'financial.approve',v_correction);
        -- Phase 2 of migration 67: re-post each Payment allocation's and Credit application's
        -- unreleased rest to the same Charge (one Late-payment Charge detail with the same basis),
        -- with its release row naming the Charge correction (owner answer 2 to Q-2026-10-09-66);
        -- released Payment value becomes Customer Credit of the Charge's Customer (BR-CREDIT-014,
        -- also when that Customer did not pay) and released Credit value returns to its Credit.
        FOR v_source IN SELECT value FROM jsonb_array_elements(v_plan->'released_sources')
            WHERE value->>'kind' IN ('PAYMENT_ALLOCATION','CREDIT_APPLICATION')
        LOOP
            v_released:=(v_source->>'released_usd_cents')::bigint;
            IF v_source->>'kind'='PAYMENT_ALLOCATION' THEN
                SELECT * INTO STRICT v_allocation FROM app.payment_allocations
                WHERE id=(v_source->>'id')::uuid;
                v_rest:=v_allocation.amount_usd_cents-v_released;
                v_new:=CASE WHEN v_rest>0 THEN gen_random_uuid() END;
                v_credit:=gen_random_uuid();
                INSERT INTO app.invoice_credit_excess_releases(id,late_payment_charge_correction_id,
                    source_kind,reversed_payment_allocation_id,replacement_payment_allocation_id,
                    customer_credit_id,released_usd_cents,reason,actor_id,created_at)
                VALUES(gen_random_uuid(),v_row,'PAYMENT_ALLOCATION',v_allocation.id,v_new,v_credit,
                    v_released,'Late-payment Charge correction credit excess',p_actor,clock_timestamp());
                IF v_new IS NOT NULL THEN
                    v_at:=app.settlement_late_charge_instant(v_charge.id,NULL);
                    PERFORM app.link_settlement_correction_effect(v_correction,'payment_allocation_id',v_new);
                    INSERT INTO app.payment_allocations(id,payment_id,target_customer_id,proposal_batch_id,
                        between_invoice_sequence,target_kind,invoice_id,late_payment_charge_id,amount_usd_cents,
                        between_invoice_basis,within_invoice_basis,customer_designation_reference,
                        selected_invoice_due_date,selected_invoice_issued_at,selected_invoice_number_snapshot,
                        proposal_generated_at,proposal_trace,posted_at,posted_by,authorization_reference)
                    VALUES(v_new,v_allocation.payment_id,v_allocation.target_customer_id,NULL,NULL,
                        'LATE_PAYMENT_CHARGE',NULL,v_charge.id,v_rest,v_allocation.between_invoice_basis,
                        v_allocation.within_invoice_basis,v_allocation.customer_designation_reference,
                        NULL,NULL,NULL,NULL,NULL,v_at,p_actor,'payments.allocate');
                    INSERT INTO app.payment_allocation_details(id,payment_allocation_id,invoice_line_id,
                        late_payment_charge_id,obligation_kind,invoice_line_category_snapshot,
                        proposed_amount_usd_cents,posted_amount_usd_cents,attribution_basis,detail_sequence,
                        calculation_trace)
                    SELECT gen_random_uuid(),v_new,NULL,detail.late_payment_charge_id,detail.obligation_kind,
                        detail.invoice_line_category_snapshot,NULL,v_rest,detail.attribution_basis,1::smallint,
                        jsonb_build_object('reason','Late-payment Charge correction credit excess',
                            'replaces_detail_id',detail.id,'late_payment_charge_correction_id',v_row)
                    FROM app.payment_allocation_details detail
                    WHERE detail.payment_allocation_id=v_allocation.id;
                END IF;
                INSERT INTO app.customer_credits(id,customer_id,source_payment_id,recognized_usd_cents,
                    customer_authorization_reference,recognized_at,recognized_by,reason,authorization_reference)
                VALUES(v_credit,v_charge.customer_id,v_allocation.payment_id,v_released,
                    'late-payment-charge-correction:' || v_row::text,
                    app.settlement_late_charge_instant(v_charge.id,NULL),p_actor,
                    'Late-payment Charge correction credit excess','credits.recognize');
            ELSE
                SELECT * INTO STRICT v_application FROM app.customer_credit_applications
                WHERE id=(v_source->>'id')::uuid;
                v_rest:=v_application.amount_usd_cents-v_released;
                v_new:=CASE WHEN v_rest>0 THEN gen_random_uuid() END;
                INSERT INTO app.invoice_credit_excess_releases(id,late_payment_charge_correction_id,
                    source_kind,reversed_credit_application_id,replacement_credit_application_id,
                    released_usd_cents,reason,actor_id,created_at)
                VALUES(gen_random_uuid(),v_row,'CREDIT_APPLICATION',v_application.id,v_new,
                    v_released,'Late-payment Charge correction credit excess',p_actor,clock_timestamp());
                IF v_new IS NOT NULL THEN
                    v_at:=app.settlement_late_charge_instant(v_charge.id,v_application.customer_credit_id);
                    -- The rest is an ordinary Credit application (no Final Settlement link); when it
                    -- re-posts a Settlement Credit application, its one-call reversal stays refused.
                    PERFORM app.link_settlement_correction_effect(v_correction,
                        'customer_credit_application_id',v_new);
                    INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,invoice_id,
                        late_payment_charge_id,final_settlement_id,amount_usd_cents,within_invoice_basis,
                        customer_designation_reference,proposal_generated_at,proposal_trace,occurred_at,
                        actor_id,authorization_reference)
                    VALUES(v_new,v_application.customer_credit_id,'LATE_PAYMENT_CHARGE',NULL,v_charge.id,NULL,
                        v_rest,v_application.within_invoice_basis,v_application.customer_designation_reference,
                        NULL,NULL,v_at,p_actor,'credits.apply');
                    INSERT INTO app.customer_credit_application_details(id,customer_credit_application_id,
                        invoice_line_id,late_payment_charge_id,obligation_kind,invoice_line_category_snapshot,
                        proposed_amount_usd_cents,applied_amount_usd_cents,attribution_basis,detail_sequence,
                        calculation_trace)
                    SELECT gen_random_uuid(),v_new,NULL,detail.late_payment_charge_id,detail.obligation_kind,
                        detail.invoice_line_category_snapshot,NULL,v_rest,detail.attribution_basis,1::smallint,
                        jsonb_build_object('reason','Late-payment Charge correction credit excess',
                            'replaces_detail_id',detail.id,'late_payment_charge_correction_id',v_row)
                    FROM app.customer_credit_application_details detail
                    WHERE detail.customer_credit_application_id=v_application.id;
                END IF;
                v_credit:=v_application.customer_credit_id;
            END IF;
            v_paid:=v_paid||jsonb_build_array(jsonb_build_object('customer_credit_id',v_credit,
                'released_usd_cents',v_released));
        END LOOP;
        -- The shared DL-032 step (sub-slice 10c-2a-2; owner answers 1 and 2 to Q-2026-10-07-42):
        -- under the same locks, the plan check again on the real state (stale P5S02 otherwise), then
        -- each Customer's Credit, the Deposit applications and the Deposit Refunds of the plan.
        v_step:=app.post_settlement_correction_plan(p_property,p_actor,p_draft);
        -- One Credit Refund per released Payment allocation or Credit application, paid to that
        -- Credit's Customer (BR-CREDIT-014) with the draft's method and note in its own details row
        -- (BR-REFUND-014), for the value left in its Credit after the step and at most what this
        -- correction released to it (owner answer 2 to Q-2026-10-07-42).
        FOR v_source IN SELECT value FROM jsonb_array_elements(v_paid) LOOP
            v_credit:=(v_source->>'customer_credit_id')::uuid;
            v_released:=(v_source->>'released_usd_cents')::bigint;
            IF NOT v_left ? v_credit::text THEN
                v_left:=v_left||jsonb_build_object(v_credit::text,app.credit_available_value(v_credit));
            END IF;
            v_pay:=LEAST(v_released,(v_left->>v_credit::text)::bigint);
            CONTINUE WHEN v_pay<=0;
            v_left:=jsonb_set(v_left,ARRAY[v_credit::text],to_jsonb((v_left->>v_credit::text)::bigint-v_pay));
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
            VALUES(v_refund_id,'REF-' || v_refund_id::text,v_recipient,NULL,v_credit,v_pay,'USD',
                v_pay,v_draft.reason,v_at,p_actor,'refunds.create');
            v_refunds:=v_refunds||jsonb_build_array(jsonb_build_object('refund_id',v_refund_id,
                'customer_credit_id',v_credit,'recipient_customer_id',v_recipient,
                'amount_usd_cents',v_pay));
        END LOOP;
        -- Every linked record is written: the deferred checks run now, inside this definer
        -- function, as the existing writers run them (sub-slice 10b plan note); the Charge
        -- correction's validator refuses a result below the active applications (23514).
        SET CONSTRAINTS ALL IMMEDIATE;
        v_after:=app.late_payment_charge_snapshot(v_charge.id);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
            entity_id,reason,authorization_reference,property_id,previous_state,resulting_state,
            correlation_id,source,outcome,authorization_evidence,linked_source_event_id,customer_id,
            lease_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'late_payment.charge_corrected',
            'late_payment_charge',v_charge.id,v_draft.reason,'financial.approve',p_property,v_before,
            v_after,v_correction,'API','SUCCEEDED',
            v_evidence || jsonb_build_object('kind',v_kind,'amount_usd_cents',v_amount),
            v_row,v_charge.customer_id,v_lease);
        v_result:=app.settlement_late_charge_refund_result(p_draft);
        INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
            reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
            source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
        VALUES (gen_random_uuid(),v_now,v_business_date,p_actor,'final_settlement.correction.confirmed',
            'settlement_correction',v_correction,v_draft.reason,'financial.approve',p_property,
            '{}'::jsonb,
            jsonb_build_object('settlement_correction_id',v_correction,
                'final_settlement_id',v_settlement.id,'variant','REFUND',
                'target_kind','LATE_PAYMENT_CHARGE','late_payment_charge_id',v_charge.id,
                'late_payment_charge_correction_id',v_row,'correction_kind',v_kind,
                'customer_id',v_charge.customer_id,'amount_usd_cents',v_amount,
                'refund_method_id',v_method,'refunds',v_refunds,
                -- Every reversal, re-post and released Credit the generic audits record without
                -- the correction is named here (design note point 2), and every record the shared
                -- step wrote.
                'released_sources',v_result->'released_sources',
                'credit_application_ids',v_step->'credit_application_ids',
                'deposit_application_ids',v_step->'deposit_application_ids',
                'deposit_refund_ids',v_step->'refund_ids'),
            v_correction,'API','SUCCEEDED',v_evidence,v_charge.customer_id,v_lease,v_unit);
        RETURN v_result;
    END $$;
"""

INTERNAL = (
    "app.settlement_late_charge_refund_input(jsonb)",
    "app.settlement_late_charge_refund_sources(uuid)",
    "app.settlement_late_charge_refund_source_state(uuid,uuid)",
    "app.settlement_late_charge_refund_overlay(jsonb,uuid)",
    "app.settlement_late_charge_refund_plan(uuid,uuid,jsonb)",
    "app.settlement_late_charge_refund_result(uuid)",
    "app.settlement_late_charge_instant(uuid,uuid)",
)
RECORD = "app.record_settlement_late_charge_refund_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_late_charge_refund(uuid,uuid,uuid,text)"


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
            raise RuntimeError(f"Late-payment Charge Refund source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(RELEASE_TABLE)
    op.execute(SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in (*INTERNAL, RECORD, CONFIRM):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in (RECORD, CONFIRM):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Late-payment Charge Refund migration is forward-only")
