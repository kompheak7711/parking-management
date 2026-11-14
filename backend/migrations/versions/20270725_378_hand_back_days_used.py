"""DL-229 (D1, owner 12 Nov 2026): a hand-back before the 5th pays only the days used.

Before this migration the monthly Rent Invoice of the hand-back month was treated by what was
paid: an unpaid Invoice was made Void (the tenant owed nothing for the days in the Unit), a fully
paid Invoice was kept (the tenant lost the whole month), and a partly paid Invoice kept its paid
part (DL-068, DL-069). The owner decided that every tenant pays the same: the days from the 1st
to the hand-back day, by the real days of the month (BR-RENT-006). The hand-back day is a day
used.

What changes:

1. ``app.hand_back_rent_invoice_basis``: for each line it now says what is kept for the days used
   (``app.calculate_prorated_monthly_usd_cents`` of what the line charges now) and what is taken
   off by a credit Adjustment. The next month's Invoice (hand-back on or after the 25th) has no
   day used. The action is ``KEEP`` when nothing is to take off, ``VOID`` only for the next
   month's Invoice with nothing paid, and ``CREDIT_ADJUSTMENT`` in every other case.
2. ``app.resolve_hand_back_rent_invoice``: the old command is dropped and made again with one
   more parameter, the credit the caller saw. Each line gets one credit Adjustment down to the
   days used. ``app.adjust_invoice`` already gives what was paid above the new amount back as
   Customer Credit, so no payment record is changed. A fully paid Invoice can now be resolved,
   so the expected unpaid amount may be 0.
3. ``app.hand_back_rent_resolutions``: five new columns keep the numbers of the decision (days
   used, days of the month, amount kept, amount credited, amount given back as Customer Credit).
   They are empty on rows written before this migration. The check on the expected unpaid amount
   is relaxed from above 0 to 0 or more.

What stays as it was: only a verified voluntary early termination with a recorded move-out; the
5th and the 25th; one resolution for an Invoice; the right needed (``invoices.adjust`` for an
Adjustment, ``invoices.void`` for a Void); rows already written. A hand-back on the 5th or later
pays the full month.

No data is changed or deleted. Forward-only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270725_378"
down_revision: str | None = "20270724_393"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_RESOLVE = "app.resolve_hand_back_rent_invoice(uuid,uuid,uuid,uuid,text,integer,bigint,text)"
RESOLVE = "app.resolve_hand_back_rent_invoice(uuid,uuid,uuid,uuid,text,integer,bigint,bigint,text)"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.hand_back_rent_resolutions
            ADD COLUMN days_used smallint,
            ADD COLUMN days_in_month smallint,
            ADD COLUMN kept_usd_cents bigint,
            ADD COLUMN credit_usd_cents bigint,
            ADD COLUMN released_usd_cents bigint,
            DROP CONSTRAINT hand_back_rent_resolutions_expected_outstanding_usd_cents_check,
            ADD CONSTRAINT hand_back_rent_resolutions_expected_outstanding_usd_cents_check
                CHECK (expected_outstanding_usd_cents >= 0),
            ADD CONSTRAINT hand_back_rent_resolutions_days_used_numbers CHECK (
                (days_used IS NULL AND days_in_month IS NULL AND kept_usd_cents IS NULL
                    AND credit_usd_cents IS NULL AND released_usd_cents IS NULL)
                OR (days_used IS NOT NULL AND days_in_month IS NOT NULL
                    AND kept_usd_cents IS NOT NULL AND credit_usd_cents IS NOT NULL
                    AND released_usd_cents IS NOT NULL
                    AND days_used BETWEEN 0 AND 4 AND days_in_month BETWEEN 28 AND 31
                    AND (days_used = 0) = (coverage = 'NEXT_MONTH')
                    AND kept_usd_cents >= 0 AND credit_usd_cents > 0
                    AND released_usd_cents BETWEEN 0 AND credit_usd_cents
                    AND (action <> 'VOID' OR released_usd_cents = 0)));
        COMMENT ON COLUMN app.hand_back_rent_resolutions.days_used IS
            'DL-229: days from the 1st to the hand-back day; 0 for the next month''s Invoice. '
            'Empty on a row written before migration 20270725_378.';
        COMMENT ON COLUMN app.hand_back_rent_resolutions.kept_usd_cents IS
            'DL-229: what the Invoice charges after the resolution, for the days used.';
        COMMENT ON COLUMN app.hand_back_rent_resolutions.credit_usd_cents IS
            'DL-229: what the resolution took off the Invoice.';
        COMMENT ON COLUMN app.hand_back_rent_resolutions.released_usd_cents IS
            'DL-229: the part of the credit that was already paid and went back to the Customer '
            'as Customer Credit.';
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.hand_back_rent_invoice_basis(p_property uuid,p_actor uuid,p_invoice uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_invoice app.invoices%ROWTYPE; v_lease app.leases%ROWTYPE; v_move_out app.physical_move_out_events%ROWTYPE;
            v_current bigint; v_evidence text; v_coverage text; v_action text; v_month date;
            v_applied numeric; v_outstanding numeric; v_lines jsonb;
            v_days_used integer; v_days_in_month integer; v_resolved boolean;
            v_kept numeric; v_credit numeric; v_released numeric;
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL OR p_invoice IS NULL
            THEN RAISE EXCEPTION 'Hand-back assessment is invalid' USING ERRCODE='22023'; END IF;
            IF NOT EXISTS (SELECT 1 FROM app.user_accounts account
                JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
                WHERE account.actor_id=p_actor AND account.lifecycle_state='active'
                    AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Invoice command requires an active human actor' USING ERRCODE='P4506'; END IF;
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice;
            IF NOT FOUND OR app.invoice_property_id(p_invoice) IS DISTINCT FROM p_property
            THEN RAISE EXCEPTION 'Invoice was not found' USING ERRCODE='P4501'; END IF;
            IF v_invoice.primary_category<>'RENT' OR v_invoice.rent_billing_kind IS DISTINCT FROM 'RECURRING'
                OR v_invoice.lease_id IS NULL OR v_invoice.billing_period_start IS NULL
            THEN RAISE EXCEPTION 'The hand-back rule covers only monthly Rent Invoices generated on the 25th'
                USING ERRCODE='22023'; END IF;
            IF v_invoice.status NOT IN ('UNPAID','PARTIALLY_PAID','PAID')
            THEN RAISE EXCEPTION 'The hand-back rule covers only an issued Invoice that is not VOID'
                USING ERRCODE='22023'; END IF;
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_invoice.lease_id;
            v_evidence:=app.lease_termination_invoice_readiness(p_property,v_lease.id,p_actor,1,NULL)->>'evidence_status';
            IF v_evidence IS DISTINCT FROM 'VOLUNTARY_EARLY_VERIFIED' THEN
                RAISE EXCEPTION 'The hand-back rule covers only a verified voluntary early termination'
                    USING ERRCODE='22023'; END IF;
            SELECT count(*) INTO v_current FROM app.physical_move_out_events AS move_out
            WHERE move_out.lease_id=v_lease.id AND NOT EXISTS (
                SELECT 1 FROM app.physical_move_out_events AS later WHERE later.supersedes_event_id=move_out.id);
            IF v_current=0 THEN RAISE EXCEPTION 'The hand-back rule needs a recorded move-out'
                USING ERRCODE='22023'; END IF;
            IF v_current>1 THEN RAISE EXCEPTION 'The current move-out record is ambiguous'
                USING ERRCODE='55000'; END IF;
            SELECT move_out.* INTO STRICT v_move_out FROM app.physical_move_out_events AS move_out
            WHERE move_out.lease_id=v_lease.id AND NOT EXISTS (
                SELECT 1 FROM app.physical_move_out_events AS later WHERE later.supersedes_event_id=move_out.id);
            v_month:=date_trunc('month',v_invoice.billing_period_start)::date;
            v_coverage:=CASE
                WHEN extract(day FROM v_move_out.actual_move_out_date)<5
                    AND v_month=date_trunc('month',v_move_out.actual_move_out_date)::date THEN 'HAND_BACK_MONTH'
                WHEN extract(day FROM v_move_out.actual_move_out_date)>=25
                    AND v_month=(date_trunc('month',v_move_out.actual_move_out_date)+interval '1 month')::date
                    THEN 'NEXT_MONTH'
            END;
            IF v_coverage IS NULL THEN
                RAISE EXCEPTION 'The Invoice month is not covered by the hand-back date' USING ERRCODE='22023'; END IF;
            -- DL-229: the days from the 1st to the hand-back day are used; the hand-back day counts.
            -- The next month's Invoice has no day used.
            v_days_in_month:=extract(day FROM (v_month+interval '1 month - 1 day'))::integer;
            v_days_used:=CASE v_coverage WHEN 'HAND_BACK_MONTH'
                THEN extract(day FROM v_move_out.actual_move_out_date)::integer ELSE 0 END;
            -- One resolution for an Invoice: after it, what the Invoice charges is what is kept.
            v_resolved:=EXISTS(SELECT 1 FROM app.hand_back_rent_resolutions WHERE invoice_id=p_invoice);
            WITH measured AS (
                SELECT line.id,line.category,line.line_sequence,
                    app.invoice_adjusted_line_obligation(line.id) AS owed,
                    app.invoice_line_application_value_at(line.id,'infinity') AS applied,
                    app.invoice_line_outstanding(line.id) AS outstanding
                FROM app.invoice_lines AS line WHERE line.invoice_id=p_invoice
            ), decided AS (
                SELECT measured.*,
                    CASE WHEN v_resolved THEN measured.owed
                        WHEN v_days_used=0 OR measured.owed<=0 THEN 0
                        ELSE app.calculate_prorated_monthly_usd_cents(
                            measured.owed,v_month,v_move_out.actual_move_out_date) END AS kept
                FROM measured
            )
            SELECT COALESCE(sum(applied),0),COALESCE(sum(outstanding),0),COALESCE(sum(kept),0),
                COALESCE(sum(greatest(owed-kept,0)),0),COALESCE(sum(greatest(applied-kept,0)),0),
                COALESCE(jsonb_agg(jsonb_build_object('invoice_line_id',id,'category',category,
                    'line_sequence',line_sequence,'applied_usd_cents',applied,
                    'outstanding_usd_cents',outstanding,'kept_usd_cents',kept,
                    'credit_usd_cents',greatest(owed-kept,0),
                    'released_usd_cents',greatest(applied-kept,0))
                    ORDER BY line_sequence,id),'[]'::jsonb)
            INTO v_applied,v_outstanding,v_kept,v_credit,v_released,v_lines
            FROM decided;
            v_action:=CASE WHEN v_credit=0 THEN 'KEEP'
                WHEN v_coverage='NEXT_MONTH' AND v_applied=0 THEN 'VOID'
                ELSE 'CREDIT_ADJUSTMENT' END;
            RETURN jsonb_build_object('invoice_id',p_invoice,'invoice_version',v_invoice.version,
                'invoice_status',v_invoice.status,'billing_period_start',v_invoice.billing_period_start,
                'coverage',v_coverage,'action',v_action,
                'days_used',v_days_used,'days_in_month',v_days_in_month,
                'applied_usd_cents',v_applied,'outstanding_usd_cents',v_outstanding,
                'kept_usd_cents',v_kept,'credit_usd_cents',v_credit,'released_usd_cents',v_released,
                'lines',v_lines,
                'lease_id',v_lease.id,'customer_id',v_invoice.customer_id,
                'physical_move_out_event_id',v_move_out.id,'hand_back_date',v_move_out.actual_move_out_date);
        END $$;
        """
    )
    op.execute(f"DROP FUNCTION {OLD_RESOLVE}")
    op.execute(
        """
        CREATE FUNCTION app.resolve_hand_back_rent_invoice(p_property uuid,p_actor uuid,p_invoice uuid,
            p_key uuid,p_expected_action text,p_expected_version integer,p_expected_outstanding bigint,
            p_expected_credit bigint,p_reason text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_existing app.hand_back_rent_resolutions%ROWTYPE; v_invoice app.invoices%ROWTYPE;
            v_basis jsonb; v_line jsonb; v_version integer; v_adjustment uuid; v_adjustments uuid[]:='{}';
            v_void_event uuid; v_line_id uuid; v_amount bigint; v_digest text; v_result jsonb; v_response jsonb;
            v_now timestamptz; v_timezone text; v_audit uuid; v_capability text; v_resolution uuid:=gen_random_uuid();
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL OR p_invoice IS NULL
                OR p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000'
                OR p_expected_action IS NULL OR p_expected_action NOT IN ('VOID','CREDIT_ADJUSTMENT')
                OR p_expected_version IS NULL OR p_expected_version<1
                OR p_expected_outstanding IS NULL OR p_expected_outstanding<0
                OR p_expected_credit IS NULL OR p_expected_credit<1
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Hand-back resolution is invalid' USING ERRCODE='22023'; END IF;
            v_timezone:=app.require_invoice_command_actor(p_property,p_actor);
            -- One request per key at a time, so a concurrent repeat replays the stored response.
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                'hand-back-rent:' || p_property::text || ':' || p_actor::text || ':' || p_key::text,0));
            SELECT * INTO v_existing FROM app.hand_back_rent_resolutions
            WHERE property_id=p_property AND actor_id=p_actor AND idempotency_key=p_key;
            IF FOUND THEN
                -- A row written before DL-229 has no credit number: its credit was the unpaid amount.
                IF v_existing.invoice_id IS DISTINCT FROM p_invoice
                    OR v_existing.action IS DISTINCT FROM p_expected_action
                    OR v_existing.expected_version IS DISTINCT FROM p_expected_version
                    OR v_existing.expected_outstanding_usd_cents IS DISTINCT FROM p_expected_outstanding
                    OR COALESCE(v_existing.credit_usd_cents,v_existing.expected_outstanding_usd_cents)
                        IS DISTINCT FROM p_expected_credit
                    OR v_existing.reason IS DISTINCT FROM p_reason
                THEN RAISE EXCEPTION 'Hand-back resolution key was reused' USING ERRCODE='P4505'; END IF;
                RETURN v_existing.response_body;
            END IF;
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice FOR UPDATE;
            IF NOT FOUND OR app.invoice_property_id(p_invoice) IS DISTINCT FROM p_property
            THEN RAISE EXCEPTION 'Invoice was not found' USING ERRCODE='P4501'; END IF;
            -- The termination and the current move-out must not change while this command runs.
            IF v_invoice.lease_id IS NOT NULL THEN
                PERFORM 1 FROM app.leases WHERE id=v_invoice.lease_id FOR SHARE NOWAIT;
            END IF;
            IF EXISTS (SELECT 1 FROM app.hand_back_rent_resolutions WHERE invoice_id=p_invoice) THEN
                RAISE EXCEPTION 'The Invoice already has a hand-back resolution' USING ERRCODE='P4503'; END IF;
            IF v_invoice.version<>p_expected_version THEN
                RAISE EXCEPTION 'Invoice version:%',v_invoice.version USING ERRCODE='P4504'; END IF;
            v_basis:=app.hand_back_rent_invoice_basis(p_property,p_actor,p_invoice);
            IF v_basis->>'action'='KEEP' THEN
                RAISE EXCEPTION 'The hand-back Invoice already charges only the days used'
                    USING ERRCODE='22023'; END IF;
            IF v_basis->>'action'<>p_expected_action
                OR (v_basis->>'outstanding_usd_cents')::numeric<>p_expected_outstanding
                OR (v_basis->>'credit_usd_cents')::numeric<>p_expected_credit
            THEN RAISE EXCEPTION 'The hand-back assessment changed' USING ERRCODE='P4503'; END IF;
            v_capability:=CASE p_expected_action WHEN 'VOID' THEN 'invoices.void' ELSE 'invoices.adjust' END;
            IF p_expected_action='VOID' THEN
                v_void_event:=gen_random_uuid();
                v_digest:=encode(sha256(convert_to(concat_ws('|','hand-back-rent','void',p_invoice,
                    p_expected_version,p_expected_outstanding,p_reason,p_key),'UTF8')),'hex');
                v_result:=app.void_invoice(p_property,p_invoice,p_actor,
                    md5('hand-back-rent|void|' || p_key::text)::uuid,v_digest,p_expected_version,
                    p_reason,v_void_event,gen_random_uuid());
                IF NOT EXISTS (SELECT 1 FROM app.invoice_void_events
                    WHERE id=v_void_event AND invoice_id=p_invoice)
                THEN RAISE EXCEPTION 'Hand-back VOID did not record its own VOID event' USING ERRCODE='55000'; END IF;
            ELSE
                v_version:=p_expected_version;
                FOR v_line IN SELECT value FROM jsonb_array_elements(v_basis->'lines')
                LOOP
                    -- DL-229: each line goes down to the days used. app.adjust_invoice gives what
                    -- was paid above the new amount back to the Customer as Customer Credit.
                    CONTINUE WHEN (v_line->>'credit_usd_cents')::numeric<=0;
                    v_adjustment:=gen_random_uuid();
                    v_line_id:=(v_line->>'invoice_line_id')::uuid;
                    v_amount:=(v_line->>'credit_usd_cents')::bigint;
                    v_digest:=encode(sha256(convert_to(concat_ws('|','hand-back-rent','adjust',p_invoice,
                        v_line_id,v_amount,p_expected_version,p_reason,p_key),'UTF8')),'hex');
                    -- app.adjust_invoice ends with SET CONSTRAINTS ALL IMMEDIATE, which stays in force;
                    -- defer again so each call checks its deferred constraints after its own update,
                    -- as it does when called alone (precedent: migrations 39 and 41).
                    SET CONSTRAINTS ALL DEFERRED;
                    v_result:=app.adjust_invoice(p_property,p_invoice,v_line_id,p_actor,
                        md5('hand-back-rent|adjust|' || p_key::text || '|' || v_line_id::text)::uuid,
                        v_digest,v_version,'CREDIT',v_amount,
                        'hand-back-rent-resolution:' || v_resolution::text,p_reason,
                        v_adjustment,gen_random_uuid());
                    IF NOT EXISTS (SELECT 1 FROM app.invoice_adjustments WHERE id=v_adjustment
                        AND invoice_id=p_invoice AND invoice_line_id=v_line_id
                        AND adjustment_type='CREDIT' AND amount_usd_cents=v_amount)
                    THEN RAISE EXCEPTION 'Hand-back Adjustment did not record its own Adjustment'
                        USING ERRCODE='55000'; END IF;
                    v_adjustments:=v_adjustments || v_adjustment;
                    SELECT version INTO STRICT v_version FROM app.invoices WHERE id=p_invoice;
                END LOOP;
            END IF;
            v_now:=clock_timestamp();
            v_response:=jsonb_build_object('invoice',v_result,'coverage',v_basis->'coverage',
                'action',p_expected_action,'adjustment_ids',to_jsonb(v_adjustments),'reason',p_reason,
                'days_used',v_basis->'days_used','days_in_month',v_basis->'days_in_month',
                'kept_usd_cents',v_basis->'kept_usd_cents','credit_usd_cents',v_basis->'credit_usd_cents',
                'released_usd_cents',v_basis->'released_usd_cents');
            v_audit:=gen_random_uuid();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
                source,outcome,authorization_evidence,customer_id,lease_id)
            VALUES(v_audit,v_now,timezone(v_timezone,v_now)::date,p_actor,'invoice.hand_back_rent.resolved',
                'invoice',p_invoice,p_reason,v_capability,p_property,
                v_basis-ARRAY['customer_id'],v_response,p_key,'API','SUCCEEDED',
                jsonb_build_object('capability',v_capability,'rule','BR-RENT-012','decision','DL-229',
                    'physical_move_out_event_id',v_basis->'physical_move_out_event_id'),
                (v_basis->>'customer_id')::uuid,(v_basis->>'lease_id')::uuid);
            INSERT INTO app.hand_back_rent_resolutions(id,property_id,actor_id,idempotency_key,invoice_id,lease_id,
                physical_move_out_event_id,hand_back_date,coverage,action,authorization_reference,
                expected_version,expected_outstanding_usd_cents,reason,invoice_void_event_id,adjustment_ids,
                audit_event_id,response_body,recorded_at,
                days_used,days_in_month,kept_usd_cents,credit_usd_cents,released_usd_cents)
            VALUES(v_resolution,p_property,p_actor,p_key,p_invoice,(v_basis->>'lease_id')::uuid,
                (v_basis->>'physical_move_out_event_id')::uuid,(v_basis->>'hand_back_date')::date,
                v_basis->>'coverage',p_expected_action,v_capability,p_expected_version,p_expected_outstanding,
                p_reason,v_void_event,v_adjustments,v_audit,v_response,v_now,
                (v_basis->>'days_used')::smallint,(v_basis->>'days_in_month')::smallint,
                (v_basis->>'kept_usd_cents')::bigint,(v_basis->>'credit_usd_cents')::bigint,
                (v_basis->>'released_usd_cents')::bigint);
            RETURN v_response;
        END $$;
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {RESOLVE} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {RESOLVE} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
