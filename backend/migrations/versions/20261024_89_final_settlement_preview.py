# ruff: noqa: E501
"""Final Settlement preview (V1-056 sub-slice 8b).

BR-SETTLE-002, BR-SETTLE-003, BR-SETTLE-011, DL-032; owner answers to Q-2026-10-05-20,
Q-2026-10-05-21, Q-2026-10-05-23 and Q-2026-10-05-24 (2026-10-05).

- app.final_settlement_preview (runtime role; the application checks final_settlements.prepare
  or financial.approve, the database checks the active human actor and the Property) reads one
  Final Settlement: the open obligations per Customer (Invoice lines and Late-payment Charges of
  every issued, non-VOID Invoice of the Lease, whoever is named on it), each Customer's available
  Credit (a Credit stays with its own Customer), both Deposits with the held amount and their
  path, the DL-032 steps with what each may use, and the blocking issues. It writes nothing.
  A pending draft on a Settlement source blocks for every reader, but its identity is shown only
  to a financial.approve holder or a holder of that draft's prepare capability (the slice 2 and
  6b read rule; the application passes the reader's capabilities).
- Owner answers to Q-2026-10-05-25: the cleaning check uses the Unit's current rate; the staff
  step for the remaining Pet Deposit stays everywhere except the three BR-DEP-027 terminations;
  UTILITY_PERIOD_NOT_BILLED and ONE_TIME_CHARGE_NOT_INVOICED are blocking issues. A Deposit with
  a ground and nothing held has the path NOTHING_HELD (nothing to forfeit, apply or refund).
- Owner answer to Q-2026-10-05-27: a one-time charge whose Invoice was VOIDed, or that a draft
  correction replaced, does not block; a VOIDed charge not billed again is listed under
  "information" for the approver (BR-SETTLE-003: only valid obligations).
- The Deposit path (owner answer to Q-2026-10-05-24): a Deposit with an active forfeiture is
  KEPT and never applied; a Deposit whose termination record gives a forfeiture ground and that
  was never forfeited needs its forfeiture draft confirmed (FORFEITURE_REQUIRED, a blocking
  issue); a Deposit with no ground, or whose every forfeiture was reversed, follows DL-032. The
  same rule covers a Pet Deposit kept for pet noncompliance (BR-DEP-022).
- Relaxing change of the 8a-1 Deposit application guard: it now refuses every path except
  DL_032, so a Deposit whose forfeiture was reversed may be applied (it refused it before). The
  termination record lookup moves into one shared function; app.lease_deposit_kept_rule keeps
  its behavior and delegates to it.
"""

from alembic import op
from sqlalchemy import text

revision = "20261024_89"
down_revision = "20261023_88"
branch_labels = None
depends_on = None

PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"
INTERNAL = (
    "app.lease_termination_forfeiture_rule(uuid,uuid,text)",
    "app.lease_deposit_settlement_path(uuid,uuid)",
)

KEPT_CHECK_BEFORE = (
    "            IF app.lease_deposit_kept_rule(v_settlement.property_id,NEW.deposit_id) IS NOT NULL\n"
    "                OR EXISTS(SELECT 1 FROM app.deposit_dispositions disposition\n"
    "                    WHERE disposition.deposit_id=NEW.deposit_id AND NOT EXISTS(\n"
    "                        SELECT 1 FROM app.deposit_disposition_reversals reversal\n"
    "                        WHERE reversal.deposit_disposition_id=disposition.id))\n"
)
KEPT_CHECK_AFTER = (
    "            -- A Deposit whose every forfeiture was reversed follows DL-032 (Q-2026-10-05-24).\n"
    "            IF app.lease_deposit_settlement_path(v_settlement.property_id,NEW.deposit_id)->>'path'\n"
    "                IS DISTINCT FROM 'DL_032'\n"
)


def _patch(signature: str, before: str, after: str) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    if definition.count(before) != 1:
        raise RuntimeError(f"Final Settlement preview source contract changed: {signature}")
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition.replace(before, after))


def upgrade() -> None:
    op.execute("""
        -- The forfeiture ground the termination record gives a Deposit type (the slice 6 rule),
        -- shared by the kept rule, the Settlement path and the preview.
        CREATE FUNCTION app.lease_termination_forfeiture_rule(p_property uuid,p_lease uuid,p_deposit_type text)
        RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_lease app.leases%ROWTYPE; v_event app.lease_commands%ROWTYPE; v_basis text; v_events bigint;
        BEGIN
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=p_lease;
            IF v_lease.status IS DISTINCT FROM 'TERMINATED' THEN
                RAISE EXCEPTION 'The Lease is not terminated' USING ERRCODE='22023'; END IF;
            SELECT count(*) INTO v_events FROM app.lease_commands event
            WHERE event.lease_id=v_lease.id AND event.property_id=p_property AND event.action='lease.terminate'
              AND event.occurred_at=v_lease.terminated_at;
            IF v_events<>1 THEN
                RAISE EXCEPTION 'The termination record is ambiguous' USING ERRCODE='22023'; END IF;
            SELECT event.* INTO STRICT v_event FROM app.lease_commands event
            WHERE event.lease_id=v_lease.id AND event.property_id=p_property AND event.action='lease.terminate'
              AND event.occurred_at=v_lease.terminated_at;
            SELECT context.context_data->>'basis' INTO v_basis FROM app.lease_termination_contexts context
            WHERE context.command_event_id=v_event.event_id;
            RETURN app.lease_deposit_forfeiture_rule(p_deposit_type,v_event.governing_event_reference,
                v_basis,v_lease.id,v_lease.actual_termination_date,v_lease.end_date);
        END $$;

        -- Same checks and result as migration 86; the record lookup is the shared function.
        CREATE OR REPLACE FUNCTION app.lease_deposit_kept_rule(p_property uuid,p_deposit uuid)
        RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_deposit app.deposits%ROWTYPE;
        BEGIN
            SELECT * INTO v_deposit FROM app.deposits WHERE id=p_deposit;
            IF NOT FOUND OR app.deposit_property_id(p_deposit) IS DISTINCT FROM p_property
                OR v_deposit.lease_id IS NULL
            THEN RAISE EXCEPTION 'Lease Deposit was not found' USING ERRCODE='P0002'; END IF;
            RETURN app.lease_termination_forfeiture_rule(p_property,v_deposit.lease_id,v_deposit.deposit_type);
        END $$;

        -- The Settlement path of a terminated Lease's Deposit (BR-DEP-022, BR-DEP-026; owner answers
        -- to Q-2026-10-05-20, Q-2026-10-05-23 and Q-2026-10-05-24):
        --   KEPT                an active forfeiture (disposition) exists; never applied;
        --   FORFEITURE_REQUIRED the termination record gives a ground, no forfeiture was ever
        --                       confirmed and the Deposit holds money; the Settlement waits for
        --                       the forfeiture draft;
        --   NOTHING_HELD        the same, but the Deposit holds nothing, so there is nothing to
        --                       forfeit (the forfeiture draft refuses it), apply or refund;
        --   DL_032              no ground, or every confirmed forfeiture was reversed.
        CREATE FUNCTION app.lease_deposit_settlement_path(p_property uuid,p_deposit uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_ground text; v_forfeiture text;
        BEGIN
            v_ground:=app.lease_deposit_kept_rule(p_property,p_deposit);
            v_forfeiture:=CASE
                WHEN EXISTS(SELECT 1 FROM app.deposit_dispositions disposition
                    WHERE disposition.deposit_id=p_deposit AND NOT EXISTS(
                        SELECT 1 FROM app.deposit_disposition_reversals reversal
                        WHERE reversal.deposit_disposition_id=disposition.id)) THEN 'ACTIVE'
                WHEN EXISTS(SELECT 1 FROM app.deposit_dispositions disposition
                    JOIN app.deposits deposit ON deposit.id=disposition.deposit_id
                    WHERE disposition.deposit_id=p_deposit
                      AND disposition.governing_lease_id=deposit.lease_id) THEN 'REVERSED'
                ELSE 'NONE' END;
            RETURN jsonb_build_object('ground',v_ground,'forfeiture',v_forfeiture,
                'path',CASE WHEN v_forfeiture='ACTIVE' THEN 'KEPT'
                    WHEN v_ground IS NULL OR v_forfeiture='REVERSED' THEN 'DL_032'
                    WHEN app.deposit_held_value_at(p_deposit,'infinity')>0 THEN 'FORFEITURE_REQUIRED'
                    ELSE 'NOTHING_HELD' END);
        END $$;

        -- The Settlement preview (API-071 contents; the route comes in slice 11e). Read only.
        -- p_capabilities: the reader's draft capabilities on the Property, from the application. A
        -- pending draft blocks for every reader; its identity is shown only to a financial.approve
        -- holder or a holder of the draft's prepare capability (slices 2 and 6b read rule).
        CREATE FUNCTION app.final_settlement_preview(p_property uuid,p_actor uuid,p_settlement uuid,
            p_capabilities text[])
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_settlement app.final_settlements%ROWTYPE; v_lease app.leases%ROWTYPE;
            v_ground text; v_staff_pet_step boolean; v_tenant_moved_in boolean; v_moved_in boolean;
            v_move_out app.physical_move_out_events%ROWTYPE; v_final app.move_out_final_input_events%ROWTYPE;
            v_rate bigint; v_rate_found boolean:=false; v_lines jsonb; v_charges jsonb; v_people uuid[];
            v_customers jsonb; v_deposits jsonb; v_issues jsonb:='[]'::jsonb; v_open bigint; v_pet_open bigint;
            v_invoice record; v_review jsonb; v_steps jsonb; v_unbilled jsonb; v_information jsonb;
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL OR p_settlement IS NULL OR p_capabilities IS NULL
                OR cardinality(p_capabilities) NOT BETWEEN 1 AND 10
                OR array_position(p_capabilities,NULL) IS NOT NULL
            THEN RAISE EXCEPTION 'Final Settlement preview input is invalid' USING ERRCODE='22023'; END IF;
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts account
                JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
                WHERE account.actor_id=p_actor AND account.lifecycle_state='active'
                    AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Final Settlement preview needs an active person' USING ERRCODE='42501'; END IF;
            SELECT * INTO v_settlement FROM app.final_settlements
            WHERE id=p_settlement AND property_id=p_property;
            IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_settlement.lease_id;
            -- The Security-type ground names the termination: at the three BR-DEP-027 terminations
            -- the remaining Pet Deposit pays other debt only by the Customer's choice; everywhere
            -- else the DL-013 staff step stays (Q-2026-10-05-21; owner answer 2 to Q-2026-10-05-25).
            v_ground:=app.lease_termination_forfeiture_rule(p_property,v_lease.id,'SECURITY');
            v_staff_pet_step:=v_ground IS NULL OR v_ground NOT IN ('BR-LEASE-005','BR-LEASE-025','BR-LEASE-028');

            -- Open obligations of every issued, non-VOID Invoice of the Lease (owner answer 5).
            SELECT COALESCE(jsonb_agg(jsonb_build_object('invoice_id',invoice.id,'invoice_line_id',line.id,
                    'customer_id',invoice.customer_id,'category',line.category,'description',line.description,
                    'due_date',invoice.due_date,'outstanding_usd_cents',line_value.amount,
                    'pet_damage',app.invoice_line_is_pet_damage(line.id,v_lease.id))
                ORDER BY invoice.due_date,invoice.id,line.line_sequence),'[]'::jsonb)
            INTO v_lines
            FROM app.invoices invoice JOIN app.invoice_lines line ON line.invoice_id=invoice.id
            CROSS JOIN LATERAL (SELECT app.invoice_line_outstanding(line.id) AS amount) line_value
            WHERE invoice.lease_id=v_lease.id AND invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID')
                AND line_value.amount>0;
            SELECT COALESCE(jsonb_agg(jsonb_build_object('late_payment_charge_id',charge.id,
                    'source_invoice_id',charge.source_invoice_id,'customer_id',charge.customer_id,
                    'remaining_usd_cents',position.remaining_balance_usd_cents)
                ORDER BY charge.created_at,charge.id),'[]'::jsonb)
            INTO v_charges
            FROM app.late_payment_charges charge
            JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
            JOIN app.late_payment_charge_financial_position position ON position.late_payment_charge_id=charge.id
            WHERE invoice.lease_id=v_lease.id AND position.remaining_balance_usd_cents>0;
            SELECT COALESCE(sum((item->>'outstanding_usd_cents')::bigint),0)
                +(SELECT COALESCE(sum((charge_item->>'remaining_usd_cents')::bigint),0)
                    FROM jsonb_array_elements(v_charges) charge_item)
            INTO v_open FROM jsonb_array_elements(v_lines) item;
            SELECT COALESCE(sum((item->>'outstanding_usd_cents')::bigint),0) INTO v_pet_open
            FROM jsonb_array_elements(v_lines) item WHERE (item->>'pet_damage')::boolean;

            -- Each Customer: the Primary Tenant and everyone named on an issued Invoice of the Lease.
            SELECT array_agg(person ORDER BY person IS DISTINCT FROM v_lease.primary_tenant_id,person)
            INTO v_people FROM (
                SELECT v_lease.primary_tenant_id AS person
                UNION SELECT invoice.customer_id FROM app.invoices invoice
                    WHERE invoice.lease_id=v_lease.id AND invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID')
                UNION SELECT (item->>'customer_id')::uuid FROM jsonb_array_elements(v_charges) item
            ) people;
            SELECT jsonb_agg(customer ORDER BY ordinal) INTO v_customers FROM (
                SELECT people.ordinal,jsonb_build_object('customer_id',people.person,
                    'primary_tenant',people.person=v_lease.primary_tenant_id,
                    'invoice_lines',owed.lines,'late_payment_charges',owed.charges,
                    'open_total_usd_cents',owed.total,'credits',credit.items,
                    'credit_available_usd_cents',credit.total,
                    'credit_may_use_usd_cents',LEAST(credit.total,owed.total)) AS customer
                FROM unnest(v_people) WITH ORDINALITY AS people(person,ordinal)
                CROSS JOIN LATERAL (
                    SELECT COALESCE((SELECT jsonb_agg(item) FROM jsonb_array_elements(v_lines) item
                            WHERE (item->>'customer_id')::uuid=people.person),'[]'::jsonb) AS lines,
                        COALESCE((SELECT jsonb_agg(item) FROM jsonb_array_elements(v_charges) item
                            WHERE (item->>'customer_id')::uuid=people.person),'[]'::jsonb) AS charges,
                        COALESCE((SELECT sum((item->>'outstanding_usd_cents')::bigint) FROM jsonb_array_elements(v_lines) item
                            WHERE (item->>'customer_id')::uuid=people.person),0)
                        +COALESCE((SELECT sum((item->>'remaining_usd_cents')::bigint) FROM jsonb_array_elements(v_charges) item
                            WHERE (item->>'customer_id')::uuid=people.person),0) AS total
                ) owed
                -- A Customer's Credit pays only that Customer's obligations (BR-CREDIT-008); a
                -- Credit released from a moved allocation stays with its own Customer.
                CROSS JOIN LATERAL (
                    SELECT COALESCE(jsonb_agg(jsonb_build_object('customer_credit_id',available.id,
                            'available_usd_cents',available.amount) ORDER BY available.recognized_at,available.id),
                            '[]'::jsonb) AS items,
                        COALESCE(sum(available.amount),0)::bigint AS total
                    FROM (SELECT credit.id,credit.recognized_at,app.credit_available_value(credit.id) AS amount
                        FROM app.customer_credits credit JOIN app.payments payment ON payment.id=credit.source_payment_id
                        WHERE credit.customer_id=people.person AND payment.property_id=p_property) available
                    WHERE available.amount>0
                ) credit
            ) customers;

            SELECT COALESCE(jsonb_agg(jsonb_build_object('deposit_id',deposit.id,'deposit_type',deposit.deposit_type,
                    'customer_id',deposit.customer_id,
                    'held_usd_cents',app.deposit_held_value_at(deposit.id,'infinity'))
                    ||app.lease_deposit_settlement_path(p_property,deposit.id)
                ORDER BY deposit.deposit_type DESC,deposit.id),'[]'::jsonb)
            INTO v_deposits
            FROM app.deposits deposit
            WHERE deposit.lease_id=v_lease.id AND deposit.deposit_type IN ('SECURITY','PET');

            -- Blocking issues (BR-SETTLE-011 and the plan's slice 8 notes).
            IF v_settlement.closed_at IS NOT NULL THEN
                v_issues:=v_issues||jsonb_build_object('code','SETTLEMENT_CLOSED');
            END IF;
            v_tenant_moved_in:=EXISTS(SELECT 1 FROM app.occupancies occupancy
                WHERE occupancy.lease_id=v_lease.id AND occupancy.customer_id=v_lease.primary_tenant_id);
            v_moved_in:=EXISTS(SELECT 1 FROM app.occupancies occupancy WHERE occupancy.lease_id=v_lease.id);
            SELECT move_out.* INTO v_move_out FROM app.physical_move_out_events move_out
            WHERE move_out.lease_id=v_lease.id AND NOT EXISTS(
                SELECT 1 FROM app.physical_move_out_events later WHERE later.supersedes_event_id=move_out.id);
            -- Final Utility (migration 72): only when the Primary Tenant moved in, as the command needs.
            IF v_tenant_moved_in THEN
                IF v_move_out.id IS NULL THEN
                    v_issues:=v_issues||jsonb_build_object('code','FINAL_UTILITY_NOT_ISSUED',
                        'reason','MOVE_OUT_NOT_RECORDED');
                ELSE
                    SELECT event.* INTO v_final FROM app.move_out_final_input_events event
                    WHERE event.lease_id=v_lease.id AND event.move_out_event_id=v_move_out.id AND NOT EXISTS(
                        SELECT 1 FROM app.move_out_final_input_events later WHERE later.supersedes_event_id=event.id);
                    IF v_final.id IS NULL THEN
                        v_issues:=v_issues||jsonb_build_object('code','FINAL_UTILITY_NOT_ISSUED',
                            'reason','FINAL_INPUTS_NOT_RECORDED');
                    ELSIF EXISTS(SELECT 1 FROM app.move_out_final_input_items item
                        WHERE item.event_id=v_final.id AND item.resolution='UNRESOLVED') THEN
                        v_issues:=v_issues||jsonb_build_object('code','FINAL_UTILITY_NOT_ISSUED',
                            'reason','FINAL_INPUT_UNRESOLVED','final_input_event_id',v_final.id);
                    ELSIF NOT EXISTS(SELECT 1 FROM app.utility_invoice_commands command
                            WHERE command.action='FINAL' AND command.final_input_event_id=v_final.id)
                        AND (
                            -- A final Reading with consumption not yet in a period ...
                            EXISTS(SELECT 1 FROM app.move_out_final_input_items item
                                WHERE item.event_id=v_final.id AND item.resolution='READING'
                                  AND NOT EXISTS(SELECT 1 FROM app.utility_consumption_periods period
                                      JOIN app.utility_readings reading ON reading.id=period.end_reading_id
                                      WHERE period.unit_id=v_lease.unit_id AND period.calculation_kind='ACTUAL'
                                        AND reading.meter_id=item.meter_id AND period.end_date>=item.reading_date)
                                  AND app.utility_reading_effective_value(item.reading_id) IS DISTINCT FROM (
                                      SELECT app.utility_reading_effective_value(earlier.id)
                                      FROM app.utility_readings earlier
                                      WHERE earlier.meter_id=item.meter_id AND earlier.validated_at IS NOT NULL
                                        AND earlier.reading_date<item.reading_date
                                      ORDER BY earlier.reading_date DESC,earlier.id DESC LIMIT 1))
                            -- ... or a period of this Lease with consumption on no Invoice.
                            OR EXISTS(SELECT 1 FROM app.utility_consumption_periods period
                                CROSS JOIN LATERAL app.utility_period_responsibility(period.unit_id,
                                    period.start_date,period.end_date) responsibility
                                WHERE period.unit_id=v_lease.unit_id AND responsibility.outcome='RESPONSIBLE'
                                  AND responsibility.lease_id=v_lease.id AND period.consumption_quantity>0
                                  AND NOT EXISTS(SELECT 1 FROM app.invoice_lines line
                                      WHERE line.utility_consumption_period_id=period.id)))
                    THEN
                        v_issues:=v_issues||jsonb_build_object('code','FINAL_UTILITY_NOT_ISSUED',
                            'reason','FINAL_INVOICE_NOT_ISSUED','final_input_event_id',v_final.id);
                    END IF;
                END IF;
            END IF;
            -- Utility periods this Lease is responsible for, with consumption and on no Invoice line,
            -- whether or not the final Utility Invoice exists (owner answer 3 to Q-2026-10-05-25;
            -- after the final Invoice only the catch-up command bills them, migration 73).
            v_issues:=v_issues||COALESCE((SELECT jsonb_agg(jsonb_build_object('code','UTILITY_PERIOD_NOT_BILLED',
                    'utility_consumption_period_id',period.id,'utility_type',period.utility_type,
                    'start_date',period.start_date,'end_date',period.end_date)
                    ORDER BY period.start_date,period.utility_type,period.id)
                FROM app.utility_consumption_periods period
                CROSS JOIN LATERAL app.utility_period_responsibility(period.unit_id,
                    period.start_date,period.end_date) responsibility
                WHERE period.unit_id=v_lease.unit_id AND responsibility.outcome='RESPONSIBLE'
                  AND responsibility.lease_id=v_lease.id AND period.consumption_quantity>0
                  AND NOT EXISTS(SELECT 1 FROM app.invoice_lines line
                      WHERE line.utility_consumption_period_id=period.id)),'[]'::jsonb);
            -- Cleaning charge (slice 4, plan Q13 and Q14; owner answer 1 to Q-2026-10-05-25): the
            -- Customer moved in and moved out, the Unit's current rate (the one the command charges)
            -- is above zero or not set, and no cleaning charge sits on an issued, non-VOID Invoice.
            IF v_moved_in AND v_move_out.id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM app.unit_cleaning_charges cleaning
                JOIN app.invoice_lines line ON line.authorized_obligation_id=cleaning.obligation_id
                JOIN app.invoices invoice ON invoice.id=line.invoice_id
                WHERE cleaning.lease_id=v_lease.id AND invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID'))
            THEN
                SELECT rate.rate_usd_cents,true INTO v_rate,v_rate_found FROM app.unit_cleaning_rates rate
                WHERE rate.unit_id=v_lease.unit_id AND NOT EXISTS(
                    SELECT 1 FROM app.unit_cleaning_rates later WHERE later.supersedes_rate_id=rate.id);
                IF NOT COALESCE(v_rate_found,false) OR v_rate>0 THEN
                    v_issues:=v_issues||jsonb_build_object('code','CLEANING_CHARGE_MISSING',
                        'reason',CASE WHEN COALESCE(v_rate_found,false) THEN 'NOT_ISSUED' ELSE 'NO_RATE' END,
                        'rate_usd_cents',v_rate);
                END IF;
            END IF;
            -- Every Late-payment Decision the existing review allows (owner answer 6).
            FOR v_invoice IN SELECT invoice.id,invoice.customer_id FROM app.invoices invoice
                WHERE invoice.lease_id=v_lease.id AND invoice.status IN ('UNPAID','PARTIALLY_PAID')
                ORDER BY invoice.due_date,invoice.id
            LOOP
                v_review:=app.late_payment_review_snapshot(v_invoice.id);
                IF (v_review->>'eligible')::boolean THEN
                    v_issues:=v_issues||jsonb_build_object('code','LATE_PAYMENT_DECISION_MISSING',
                        'invoice_id',v_invoice.id,'customer_id',v_invoice.customer_id);
                END IF;
            END LOOP;
            -- A Deposit with a ground and no confirmed forfeiture (Q-2026-10-05-24).
            v_issues:=v_issues||COALESCE((SELECT jsonb_agg(jsonb_build_object('code','FORFEITURE_NOT_CONFIRMED',
                    'deposit_id',item->'deposit_id','deposit_type',item->'deposit_type','ground',item->'ground')
                    ORDER BY item->>'deposit_type' DESC,item->>'deposit_id')
                FROM jsonb_array_elements(v_deposits) item WHERE item->>'path'='FORFEITURE_REQUIRED'),'[]'::jsonb);
            -- A pending forfeiture, reversal, Refund or Payment move draft on a Settlement source.
            v_issues:=v_issues||COALESCE((SELECT jsonb_agg(CASE
                    WHEN 'financial.approve'=ANY(p_capabilities) OR draft.prepare_capability=ANY(p_capabilities)
                    THEN jsonb_build_object('code','PENDING_DRAFT','draft_id',draft.id,'kind',draft.kind,
                        'variant',draft.payload->>'variant')
                    ELSE jsonb_build_object('code','PENDING_DRAFT') END
                    ORDER BY draft.prepared_at,draft.id)
                FROM app.financial_drafts draft
                WHERE draft.property_id=p_property AND draft.kind IN ('REFUND','DEPOSIT_FORFEITURE','PAYMENT_MOVE')
                  AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision WHERE decision.draft_id=draft.id)
                  AND (draft.payload->>'deposit_id' IN (SELECT deposit.id::text FROM app.deposits deposit
                          WHERE deposit.lease_id=v_lease.id)
                      OR (draft.kind='REFUND' AND draft.payload->>'source_kind'='CREDIT'
                          AND draft.payload->>'source_id' IN (SELECT credit.id::text FROM app.customer_credits credit
                              WHERE credit.customer_id=ANY(v_people)))
                      OR (draft.kind='REFUND' AND draft.payload->>'source_kind'='PAYMENT'
                          AND draft.payload->>'source_id' IN (SELECT payment.id::text FROM app.payments payment
                              WHERE payment.payer_customer_id=ANY(v_people)))
                      OR (draft.kind='PAYMENT_MOVE' AND (
                          draft.payload->>'target_invoice_id' IN (SELECT invoice.id::text FROM app.invoices invoice
                              WHERE invoice.lease_id=v_lease.id)
                          OR draft.payload->>'source_allocation_id' IN (SELECT allocation.id::text
                              FROM app.payment_allocations allocation
                              LEFT JOIN app.late_payment_charges charge ON charge.id=allocation.late_payment_charge_id
                              JOIN app.invoices invoice ON invoice.id=COALESCE(allocation.invoice_id,charge.source_invoice_id)
                              WHERE invoice.lease_id=v_lease.id))))),'[]'::jsonb);
            -- One-time charge sources of the Lease (Damage, Miscellaneous or the cleaning charge) on
            -- no DRAFT or issued, non-VOID Invoice (owner answer 4 to Q-2026-10-05-25). Only a
            -- charge still waiting to be billed blocks; a charge whose Invoice was VOIDed and a
            -- charge a draft correction replaced were withdrawn with a reason, and BR-SETTLE-003
            -- counts only valid obligations (owner answer to Q-2026-10-05-27). A VOIDed charge not
            -- billed again is listed as information for the approver.
            SELECT COALESCE(jsonb_agg(jsonb_build_object('authorized_obligation_id',obligation.id,
                    'customer_id',obligation.customer_id,'category',obligation.category,
                    'amount_usd_cents',obligation.authorized_amount_usd_cents,
                    'voided',EXISTS(SELECT 1 FROM app.invoice_lines line
                        JOIN app.invoices invoice ON invoice.id=line.invoice_id
                        WHERE line.authorized_obligation_id=obligation.id AND invoice.status='VOID'),
                    'replaced',EXISTS(SELECT 1 FROM app.invoice_draft_revision_events revision
                        WHERE revision.entity_kind='LINE' AND revision.operation='UPDATE'
                          AND revision.before_state->>'authorized_obligation_id'=obligation.id::text
                          AND revision.after_state->>'authorized_obligation_id'
                              IS DISTINCT FROM obligation.id::text))
                    ORDER BY obligation.authorized_at,obligation.id),'[]'::jsonb)
            INTO v_unbilled
            FROM app.authorized_nonrecurring_obligations obligation
            WHERE obligation.lease_id=v_lease.id AND NOT EXISTS(SELECT 1 FROM app.invoice_lines line
                JOIN app.invoices invoice ON invoice.id=line.invoice_id
                WHERE line.authorized_obligation_id=obligation.id
                  AND invoice.status IN ('DRAFT','UNPAID','PARTIALLY_PAID','PAID'));
            v_issues:=v_issues||COALESCE((SELECT jsonb_agg(jsonb_build_object('code','ONE_TIME_CHARGE_NOT_INVOICED',
                    'authorized_obligation_id',item->'authorized_obligation_id',
                    'customer_id',item->'customer_id','category',item->'category') ORDER BY entry.ordinal)
                FROM jsonb_array_elements(v_unbilled) WITH ORDINALITY AS entry(item,ordinal)
                WHERE NOT (item->>'voided')::boolean AND NOT (item->>'replaced')::boolean),'[]'::jsonb);
            v_information:=COALESCE((SELECT jsonb_agg(jsonb_build_object('code','VOIDED_CHARGE_NOT_BILLED_AGAIN',
                    'authorized_obligation_id',item->'authorized_obligation_id',
                    'customer_id',item->'customer_id','category',item->'category',
                    'amount_usd_cents',item->'amount_usd_cents') ORDER BY entry.ordinal)
                FROM jsonb_array_elements(v_unbilled) WITH ORDINALITY AS entry(item,ordinal)
                WHERE (item->>'voided')::boolean),'[]'::jsonb);
            -- An Invoice draft of the Lease that is not issued.
            v_issues:=v_issues||COALESCE((SELECT jsonb_agg(jsonb_build_object('code','INVOICE_DRAFT_NOT_ISSUED',
                    'invoice_id',invoice.id,'customer_id',invoice.customer_id) ORDER BY invoice.created_at,invoice.id)
                FROM app.invoices invoice WHERE invoice.lease_id=v_lease.id AND invoice.status='DRAFT'),'[]'::jsonb);

            -- DL-032 in its fixed order; every amount is an upper bound, not a proposal: staff choose
            -- each step explicitly and nothing is inferred between Deposit types (BR-SETTLE-006).
            v_steps:=jsonb_build_array(
                jsonb_build_object('step',1,'kind','OBLIGATIONS_FINAL','open_total_usd_cents',v_open),
                jsonb_build_object('step',2,'kind','CUSTOMER_CREDIT','customers',COALESCE((
                    SELECT jsonb_agg(jsonb_build_object('customer_id',item->'customer_id',
                        'may_use_usd_cents',item->'credit_may_use_usd_cents'))
                    FROM jsonb_array_elements(v_customers) item),'[]'::jsonb)),
                jsonb_build_object('step',3,'kind','PET_DEPOSIT_PET_DAMAGE','pet_damage_open_usd_cents',v_pet_open,
                    'deposits',COALESCE((SELECT jsonb_agg(jsonb_build_object('deposit_id',item->'deposit_id',
                        'may_use_usd_cents',LEAST((item->>'held_usd_cents')::bigint,v_pet_open)))
                        FROM jsonb_array_elements(v_deposits) item
                        WHERE item->>'deposit_type'='PET' AND item->>'path'='DL_032'),'[]'::jsonb)),
                jsonb_build_object('step',4,'kind','SECURITY_DEPOSIT',
                    'deposits',COALESCE((SELECT jsonb_agg(jsonb_build_object('deposit_id',item->'deposit_id',
                        'may_use_usd_cents',LEAST((item->>'held_usd_cents')::bigint,v_open)))
                        FROM jsonb_array_elements(v_deposits) item
                        WHERE item->>'deposit_type'='SECURITY' AND item->>'path'='DL_032'),'[]'::jsonb)),
                jsonb_build_object('step',5,'kind','PET_DEPOSIT_REMAINDER',
                    'chosen_by',CASE WHEN v_staff_pet_step THEN 'CUSTOMER_OR_STAFF_WITH_REASON'
                        ELSE 'CUSTOMER_ONLY' END,
                    'deposits',COALESCE((SELECT jsonb_agg(jsonb_build_object('deposit_id',item->'deposit_id',
                        'may_use_usd_cents',LEAST((item->>'held_usd_cents')::bigint,v_open)))
                        FROM jsonb_array_elements(v_deposits) item
                        WHERE item->>'deposit_type'='PET' AND item->>'path'='DL_032'),'[]'::jsonb)),
                jsonb_build_object('step',6,'kind','REMAINING_BALANCE',
                    'stays_with','CUSTOMER_NAMED_ON_EACH_OBLIGATION'),
                jsonb_build_object('step',7,'kind','DEPOSIT_REFUNDS',
                    'default_recipient_customer_id',v_lease.primary_tenant_id,
                    'deposits',COALESCE((SELECT jsonb_agg(item->'deposit_id')
                        FROM jsonb_array_elements(v_deposits) item WHERE item->>'path'='DL_032'),'[]'::jsonb)));

            RETURN jsonb_build_object('settlement',app.final_settlement_json(p_settlement),
                'lease',jsonb_build_object('lease_id',v_lease.id,'primary_tenant_id',v_lease.primary_tenant_id,
                    'actual_termination_date',v_lease.actual_termination_date,'end_date',v_lease.end_date,
                    'termination_ground',v_ground,'moved_in',v_moved_in,
                    'move_out_date',v_move_out.actual_move_out_date),
                'customers',COALESCE(v_customers,'[]'::jsonb),'deposits',v_deposits,'steps',v_steps,
                'open_total_usd_cents',v_open,'blocking_issues',v_issues,'information',v_information,
                'ready',jsonb_array_length(v_issues)=0,'previewed_at',statement_timestamp());
        END $$;
    """)
    _patch("app.validate_deposit_application()", KEPT_CHECK_BEFORE, KEPT_CHECK_AFTER)
    for function in (PREVIEW, *INTERNAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {PREVIEW} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("Final Settlement preview migration is forward-only")
