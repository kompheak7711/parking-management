"""V1-058 R7a: what the Waiting for approval page shows.

DESIGN.md "Waiting for approval" (mock-up round 8): four cards (Waiting, Money out, Deposits
kept, Decided today), the list of drafts that wait (Draft, For, Prepared by, Amount, Status)
and the drafts decided today. Each kind of draft keeps its own payload, so the list needs one
plain line per draft: what it is (kind and variant), whom it is for (Customer, Lease or
Reservation, and the Unit), the amount in cents and where the money goes (OUT: paid out, KEPT:
a Deposit kept, INTERNAL: moved between records or a debt changed).

`app.financial_draft_approvals(property, actor, capabilities)` returns
`{business_date, waiting[], decided_today[]}`. Each item is the draft as
`app.financial_draft_json` gives it (without the decision's transaction id, as the other
shared draft reads since 20270208_196), plus `summary`. Only drafts prepared under one of the
capabilities passed are read, as `app.list_financial_drafts_by_capability` does; the application
passes them from the actor's grants (every prepare capability with `financial.approve`). The
amount comes from the payload as the draft recorded it; the confirm command checks every rule
again, so this line is for reading only. A payload shape the read does not know gives a NULL
amount, never an error.

Additive only: two new functions; no existing table, function or grant changes.
"""

from alembic import op

revision = "20270222_210"
down_revision = "20270221_209"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION app.financial_draft_summary(p_draft app.financial_drafts)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE
            p jsonb := p_draft.payload;
            v_variant text := p_draft.payload->>'variant';
            v_amount jsonb;
            v_cents bigint;
            v_direction text := 'INTERNAL';
            v_customer uuid;
            v_lease uuid;
            v_reservation uuid;
            v_deposit uuid;
            v_deposit_type text;
            v_unit uuid;
        BEGIN
            -- Amounts are JSON numbers of whole cents.
            v_amount := CASE
                WHEN p_draft.kind IN ('REFUND','DEPOSIT_FORFEITURE') THEN p->'amount_usd_cents'
                WHEN p_draft.kind='PAYMENT_MOVE' THEN p#>'{source,moved_usd_cents}'
                WHEN p_draft.kind='PAYMENT_RETURN'
                    THEN p#>'{source,payment,usd_accounting_value_cents}'
                WHEN p_draft.kind='ADJUSTMENT_REVERSAL' THEN p#>'{source,amount_usd_cents}'
                WHEN p_draft.kind='FINAL_SETTLEMENT' THEN (
                    SELECT to_jsonb(sum((step->>'amount_usd_cents')::numeric))
                    FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p->'steps')='array'
                        THEN p->'steps' ELSE '[]' END) step
                    WHERE step->>'kind'='DEPOSIT_REFUNDS'
                      AND jsonb_typeof(step->'amount_usd_cents')='number')
                WHEN p_draft.kind='SETTLEMENT_CORRECTION' THEN CASE v_variant
                    WHEN 'EXTRA_CHARGE' THEN p#>'{charge,amount_usd_cents}'
                    WHEN 'CHARGE_REDUCTION' THEN p#>'{reduction,amount_usd_cents}'
                    WHEN 'REFUND' THEN p#>'{refund,amount_usd_cents}'
                    WHEN 'PET_DAMAGE_RECLASSIFICATION' THEN (
                        SELECT to_jsonb(sum((item->>'amount_usd_cents')::numeric))
                        FROM jsonb_array_elements(
                            CASE WHEN jsonb_typeof(p->'reversed_applications')='array'
                                THEN p->'reversed_applications' ELSE '[]' END) item
                        WHERE jsonb_typeof(item->'amount_usd_cents')='number')
                    WHEN 'REFUND_RETURN' THEN p#>'{refund_return,returned_amount_usd_cents}'
                    WHEN 'FORFEITURE_REVERSAL' THEN p->'amount_usd_cents'
                    WHEN 'RETURNED_PAYMENT'
                        THEN p#>'{source,payment,usd_accounting_value_cents}'
                    WHEN 'DEPOSIT_RECEIPT_CORRECTION' THEN p#>'{source,receipt,amount_usd_cents}'
                    WHEN 'RETURN_REVERSAL' THEN p->'returned_amount_usd_cents'
                    WHEN 'ADJUSTMENT_REVERSAL' THEN p#>'{source,amount_usd_cents}'
                    WHEN 'PAYMENT_MOVE' THEN p#>'{source,moved_usd_cents}'
                    ELSE NULL END
                ELSE NULL END;
            IF jsonb_typeof(v_amount)='number' AND (v_amount#>>'{}')::numeric
                    BETWEEN 0 AND 9000000000000000
                AND (v_amount#>>'{}')::numeric=trunc((v_amount#>>'{}')::numeric)
            THEN v_cents := (v_amount#>>'{}')::numeric::bigint; END IF;

            IF p_draft.kind IN ('REFUND','PAYMENT_RETURN')
                OR (p_draft.kind='SETTLEMENT_CORRECTION'
                    AND v_variant IN ('REFUND','HELD_VALUE_REFUND','RETURNED_PAYMENT'))
                OR (p_draft.kind='FINAL_SETTLEMENT' AND COALESCE(v_cents,0)>0)
            THEN v_direction := 'OUT';
            ELSIF p_draft.kind='DEPOSIT_FORFEITURE'
                AND v_variant IN ('RESERVATION_OUTCOME','RESERVATION_CORRECTION','LEASE_FORFEITURE')
            THEN v_direction := 'KEPT'; END IF;

            v_customer := app.draft_uuid(COALESCE(p->>'recipient_customer_id', p->>'customer_id',
                p#>>'{source,customer_id}', p#>>'{source,payer_customer_id}',
                p#>>'{source,payment,payer_customer_id}', p#>>'{source,source_customer_id}'));
            IF v_customer IS NULL AND p->>'source_kind'='CREDIT' THEN
                SELECT credit.customer_id INTO v_customer FROM app.customer_credits credit
                WHERE credit.id=app.draft_uuid(p->>'source_id');
            ELSIF v_customer IS NULL AND p->>'source_kind'='PAYMENT' THEN
                SELECT payment.payer_customer_id INTO v_customer FROM app.payments payment
                WHERE payment.id=app.draft_uuid(p->>'source_id');
            END IF;
            v_lease := app.draft_uuid(COALESCE(p->>'lease_id', p#>>'{source,lease_id}'));
            IF v_lease IS NULL AND app.draft_uuid(p->>'final_settlement_id') IS NOT NULL THEN
                SELECT settlement.lease_id INTO v_lease FROM app.final_settlements settlement
                WHERE settlement.id=app.draft_uuid(p->>'final_settlement_id');
            END IF;
            v_reservation := app.draft_uuid(p->>'reservation_id');
            v_deposit := app.draft_uuid(p->>'deposit_id');
            IF v_deposit IS NOT NULL THEN
                SELECT COALESCE(v_lease, deposit.lease_id),
                    COALESCE(v_reservation, CASE WHEN deposit.lease_id IS NULL
                        THEN deposit.reservation_id END),
                    COALESCE(v_customer, deposit.customer_id), deposit.deposit_type
                INTO v_lease, v_reservation, v_customer, v_deposit_type
                FROM app.deposits deposit WHERE deposit.id=v_deposit;
            END IF;
            IF v_lease IS NOT NULL THEN
                SELECT lease.unit_id, COALESCE(v_customer, lease.primary_tenant_id)
                INTO v_unit, v_customer FROM app.leases lease WHERE lease.id=v_lease;
            END IF;
            IF v_unit IS NULL AND v_reservation IS NOT NULL THEN
                SELECT reservation.unit_id, COALESCE(v_customer, reservation.customer_id)
                INTO v_unit, v_customer
                FROM app.reservations reservation WHERE reservation.id=v_reservation;
            END IF;
            v_unit := COALESCE(v_unit, app.draft_uuid(p#>>'{source,target_unit_id}'),
                app.draft_uuid(p#>>'{source,source_unit_id}'));

            RETURN jsonb_build_object(
                'variant', v_variant,
                'amount_usd_cents', v_cents,
                'direction', v_direction,
                'customer_id', v_customer,
                'customer_name', (SELECT customer.legal_name FROM app.customers customer
                    WHERE customer.id=v_customer),
                'lease_id', v_lease,
                'reservation_id', v_reservation,
                'deposit_type', v_deposit_type,
                'unit_id', v_unit,
                'unit_number', (SELECT unit.unit_number FROM app.units unit
                    WHERE unit.id=v_unit AND unit.property_id=p_draft.property_id),
                'prepared_by_name', (SELECT account.display_name FROM app.user_accounts account
                    WHERE account.actor_id=p_draft.prepared_by),
                'decided_by_name', (SELECT account.display_name
                    FROM app.financial_draft_decisions decision
                    JOIN app.user_accounts account ON account.actor_id=decision.decided_by
                    WHERE decision.draft_id=p_draft.id));
        END $$;

        CREATE FUNCTION app.draft_uuid(p_text text)
        RETURNS uuid LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
            SELECT CASE WHEN p_text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                THEN p_text::uuid END
        $$;

        CREATE FUNCTION app.financial_draft_approvals(
            p_property_id uuid, p_actor_id uuid, p_capabilities text[])
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_today date;
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts account
                    JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
                    WHERE account.actor_id=p_actor_id AND account.lifecycle_state='active'
                      AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Financial draft read requires an active human actor'
                USING ERRCODE='42501'; END IF;
            IF p_capabilities IS NULL OR cardinality(p_capabilities) NOT BETWEEN 1 AND 20
                OR array_position(p_capabilities, NULL) IS NOT NULL
            THEN RAISE EXCEPTION 'Financial draft page is invalid' USING ERRCODE='22023'; END IF;
            SELECT timezone(property.timezone_name, statement_timestamp())::date INTO v_today
            FROM app.properties property WHERE property.id=p_property_id;
            IF v_today IS NULL
            THEN RAISE EXCEPTION 'Financial draft was not found' USING ERRCODE='P0002'; END IF;
            RETURN jsonb_build_object(
                'business_date', v_today,
                -- Oldest first: the draft that has waited longest is decided first. One row
                -- more than the page shows tells the route that more drafts wait.
                'waiting', (SELECT COALESCE(jsonb_agg((app.financial_draft_json(draft) #- '{decision,result,transaction_id}')
                        || jsonb_build_object('summary', app.financial_draft_summary(draft))
                        ORDER BY (draft).prepared_at, (draft).id), '[]'::jsonb)
                    FROM (SELECT draft FROM app.financial_drafts draft
                        WHERE draft.property_id=p_property_id
                          AND draft.prepare_capability=ANY(p_capabilities)
                          AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                              WHERE decision.draft_id=draft.id)
                        ORDER BY draft.prepared_at, draft.id LIMIT 201) waiting(draft)),
                'decided_today', (SELECT COALESCE(jsonb_agg((app.financial_draft_json(draft) #- '{decision,result,transaction_id}')
                        || jsonb_build_object('summary', app.financial_draft_summary(draft))
                        ORDER BY decided_at DESC, (draft).id), '[]'::jsonb)
                    FROM (SELECT draft, decision.decided_at FROM app.financial_drafts draft
                        JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
                        JOIN app.properties property ON property.id=draft.property_id
                        WHERE draft.property_id=p_property_id
                          AND draft.prepare_capability=ANY(p_capabilities)
                          AND timezone(property.timezone_name, decision.decided_at)::date=v_today
                        ORDER BY decision.decided_at DESC, draft.id LIMIT 200) decided(draft, decided_at)));
        END $$;

        COMMENT ON FUNCTION app.financial_draft_approvals(uuid,uuid,text[]) IS
            'V1-058 R7a: the drafts waiting for approval and those decided today, with one '
            'plain line each; read only.';
        REVOKE ALL ON FUNCTION app.financial_draft_summary(app.financial_drafts),
            app.draft_uuid(text), app.financial_draft_approvals(uuid,uuid,text[])
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.financial_draft_approvals(uuid,uuid,text[])
            TO prm_runtime;
        """
    )


def downgrade() -> None:
    raise RuntimeError("The Waiting for approval read is forward-only; downgrade is not supported")
