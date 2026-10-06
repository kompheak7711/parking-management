# ruff: noqa: E501
"""Final Settlement confirm and close (V1-056 sub-slice 8e-3).

BR-SETTLE-004, BR-SETTLE-007, BR-SETTLE-008, BR-SETTLE-009, BR-SETTLE-011, BR-SETTLE-012,
BR-SETTLE-015, BR-SETTLE-016, BR-AUTH-010, DL-032; DB-SETTLE-001, DB-SETTLE-002, DB-SETTLE-004,
DB-SETTLE-006; owner answers to Q-2026-10-05-20, Q-2026-10-05-23, Q-2026-10-05-24,
Q-2026-10-06-32 (answer 4), Q-2026-10-06-33 (answers 2 and 3) and Q-2026-10-06-34.

- app.confirm_final_settlement_draft (financial role; the application checks financial.approve)
  confirms a pending FINAL_SETTLEMENT draft and closes its Settlement in one transaction. Under
  its locks it runs the plan check of sub-slice 8c again and refuses a draft whose sources
  changed (stale, P5S02), leaving it pending. It then writes the decision, the Settlement Credit
  applications (8e-2 writer), the Deposit applications (8a writer), the Settlement Refunds in
  Deposit id order (8d writer), the closure snapshots, the closure and one audit event. An exact
  repeat by the same approver replays the stored result. A Settlement is never reopened.
- Closure snapshots (DB-SETTLE-002, DB-SETTLE-004, DB-SETTLE-006): every issued, non-VOID Invoice
  of the Lease (whoever is named on it), each of its lines, and every Late-payment Charge of the
  Lease's Invoices, with what is still owed after every Settlement application (paid ones with 0).
  They add up to the closing balance; the rest stays open on the ledger of the person named on
  each obligation (BR-SETTLE-016). Nothing is written off.
- Owner answer 2 to Q-2026-10-06-33 (approved tightening; the preview therefore refuses Settlement
  drafts that sub-slice 8c accepted): the preview's blocking issue RENT_PERIOD_NOT_BILLED for every
  recurring Rent month a Rent run would still bill (app.lease_is_billable_for_recurring_period)
  with no active Rent Invoice of the Lease. Owner answer to Q-2026-10-06-34: a month whose Rent
  Invoice a BR-RENT-030 hand-back resolution VOIDed is decided and does not block.
- The closure guard of sub-slice 8a-1 also checks the closure itself (plan note 3): a human
  approver with an active account, and a closure time not later than the clock. It refuses only
  closures no writer could make before.

Additive, except the approved tightening of the preview; the closure guard change refuses only
records no writer could create before.
"""

from alembic import op
from sqlalchemy import text

revision = "20261029_94"
down_revision = "20261028_93"
branch_labels = None
depends_on = None

CONFIRM = "app.confirm_final_settlement_draft(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.final_settlement_unbilled_rent_months(uuid,timestamp with time zone)",
    "app.final_settlement_deposit_application_id(uuid,integer)",
    "app.final_settlement_refund_id(uuid,uuid)",
    "app.validate_settlement_closure_item()",
    "app.assert_settlement_closure_reconciled()",
    "app.reject_settlement_closure_item_mutation()",
)
PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"
GUARD = "app.reject_final_settlement_change()"

RENT_BEFORE = "            -- An Invoice draft of the Lease that is not issued.\n"
RENT_AFTER = (
    "            -- Owner answer 2 to Q-2026-10-06-33 (sub-slice 8e-3): every recurring Rent month a\n"
    "            -- Rent run would still bill, with no active Rent Invoice of the Lease; a month whose\n"
    "            -- Rent Invoice a BR-RENT-030 hand-back resolution VOIDed is decided (Q-2026-10-06-34).\n"
    "            v_issues:=v_issues||COALESCE((SELECT jsonb_agg(jsonb_build_object('code','RENT_PERIOD_NOT_BILLED',\n"
    "                    'period_start',month.period_start,'period_end',month.period_end) ORDER BY month.period_start)\n"
    "                FROM app.final_settlement_unbilled_rent_months(v_lease.id,statement_timestamp()) month),'[]'::jsonb);\n"
    + RENT_BEFORE
)
GUARD_BEFORE = "            THEN RAISE EXCEPTION 'A Final Settlement changes only by its single closure' USING ERRCODE='23514'; END IF;\n"
GUARD_AFTER = (
    GUARD_BEFORE
    + "            -- The closure itself (sub-slice 8e-3, plan note 3): a human approver with an active\n"
    "            -- account (BR-AUTH-010; the application checks financial.approve), at a time not later\n"
    "            -- than the clock. Every closure writer inherits it.\n"
    "            IF NOT EXISTS(SELECT 1 FROM app.user_accounts account\n"
    "                JOIN app.actor_identities identity ON identity.actor_id=account.actor_id\n"
    "                WHERE account.actor_id=NEW.closed_by AND account.lifecycle_state='active'\n"
    "                  AND identity.identity_kind='HUMAN')\n"
    "            THEN RAISE EXCEPTION 'A Final Settlement is closed only by an active human approver'\n"
    "                USING ERRCODE='42501'; END IF;\n"
    "            IF NEW.closed_at>clock_timestamp()+interval '5 seconds' THEN\n"
    "                RAISE EXCEPTION 'A Final Settlement closure cannot be dated in the future' USING ERRCODE='23514';\n"
    "            END IF;\n"
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
            raise RuntimeError(f"Final Settlement confirm source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute("""
        -- The recurring Rent months a Rent run would still bill for this Lease: months inside its
        -- coverage (app.lease_is_billable_for_recurring_period, the rule of the run) with no active
        -- (non-VOID) Rent Invoice of the Lease covering them. A month whose Rent Invoice a
        -- BR-RENT-030 hand-back resolution VOIDed is decided, not unbilled (owner answer to
        -- Q-2026-10-06-34). Read by the preview (RENT_PERIOD_NOT_BILLED).
        CREATE FUNCTION app.final_settlement_unbilled_rent_months(p_lease uuid,p_as_of timestamptz)
        RETURNS TABLE(period_start date,period_end date)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT month.first,month.last
            FROM app.leases lease
            CROSS JOIN LATERAL (
                SELECT series.value::date AS first,(series.value+interval '1 month - 1 day')::date AS last
                FROM generate_series(date_trunc('month',lease.start_date::timestamp),
                    date_trunc('month',LEAST(lease.actual_termination_date,lease.end_date)::timestamp),
                    interval '1 month') AS series(value)
            ) month
            WHERE lease.id=p_lease
              AND app.lease_is_billable_for_recurring_period(lease.id,month.first,month.last,p_as_of)
              AND NOT EXISTS(SELECT 1 FROM app.invoices invoice
                  WHERE invoice.lease_id=lease.id AND invoice.status<>'VOID'
                    AND EXISTS(SELECT 1 FROM app.invoice_lines line
                        WHERE line.invoice_id=invoice.id AND line.category='RENT' AND line.source_lease_id=lease.id)
                    AND daterange(invoice.billing_period_start,invoice.billing_period_end,'[]')
                        && daterange(month.first,month.last,'[]'))
              AND NOT EXISTS(SELECT 1 FROM app.hand_back_rent_resolutions resolution
                  JOIN app.invoices voided ON voided.id=resolution.invoice_id
                  WHERE resolution.lease_id=lease.id AND resolution.action='VOID'
                    AND daterange(voided.billing_period_start,voided.billing_period_end,'[]')
                        && daterange(month.first,month.last,'[]'))
            ORDER BY month.first
        $$;

        -- Ids of what a confirmed FINAL_SETTLEMENT draft writes (step = its 1-based position), so
        -- each step and each Deposit Refund is written at most once and an exact repeat replays.
        CREATE FUNCTION app.final_settlement_deposit_application_id(p_draft uuid,p_step integer)
        RETURNS uuid LANGUAGE sql IMMUTABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT md5('final-settlement-deposit-application:' || p_draft::text || ':' || p_step::text)::uuid
        $$;
        CREATE FUNCTION app.final_settlement_refund_id(p_draft uuid,p_deposit uuid)
        RETURNS uuid LANGUAGE sql IMMUTABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT md5('final-settlement-refund:' || p_draft::text || ':' || p_deposit::text)::uuid
        $$;

        -- DB-SETTLE-002 (with the id of owner answer 4 to Q-2026-10-06-32), DB-SETTLE-004 and
        -- DB-SETTLE-006: what each obligation of the Settlement still owed at closure, after every
        -- Settlement application. Written only by the confirm, while the Settlement is open, and
        -- checked again at commit against the closure (append-only, no role may write them).
        CREATE TABLE app.settlement_invoice_items (
            final_settlement_id uuid NOT NULL REFERENCES app.final_settlements(id) ON DELETE RESTRICT,
            invoice_id uuid NOT NULL REFERENCES app.invoices(id) ON DELETE RESTRICT,
            id uuid NOT NULL UNIQUE CHECK (id<>'00000000-0000-0000-0000-000000000000'),
            outstanding_at_inclusion_usd_cents bigint NOT NULL
                CHECK (outstanding_at_inclusion_usd_cents BETWEEN 0 AND 9000000000000000),
            included_at timestamptz NOT NULL CHECK (isfinite(included_at)),
            included_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            PRIMARY KEY (final_settlement_id,invoice_id)
        );
        CREATE INDEX settlement_invoice_items_invoice_idx ON app.settlement_invoice_items(invoice_id);
        COMMENT ON TABLE app.settlement_invoice_items IS
            'Append-only Final Settlement closure snapshot of each issued, non-VOID Invoice of the Lease (DB-SETTLE-002)';
        CREATE TABLE app.settlement_late_payment_charge_items (
            final_settlement_id uuid NOT NULL REFERENCES app.final_settlements(id) ON DELETE RESTRICT,
            late_payment_charge_id uuid NOT NULL REFERENCES app.late_payment_charges(id) ON DELETE RESTRICT,
            outstanding_at_inclusion_usd_cents bigint NOT NULL
                CHECK (outstanding_at_inclusion_usd_cents BETWEEN 0 AND 9000000000000000),
            included_at timestamptz NOT NULL CHECK (isfinite(included_at)),
            included_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            PRIMARY KEY (final_settlement_id,late_payment_charge_id)
        );
        CREATE INDEX settlement_late_payment_charge_items_charge_idx
            ON app.settlement_late_payment_charge_items(late_payment_charge_id);
        COMMENT ON TABLE app.settlement_late_payment_charge_items IS
            'Append-only Final Settlement closure snapshot of each Late-payment Charge of the Lease (DB-SETTLE-004)';
        CREATE TABLE app.settlement_invoice_line_items (
            id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'),
            settlement_invoice_item_id uuid NOT NULL REFERENCES app.settlement_invoice_items(id) ON DELETE RESTRICT,
            invoice_line_id uuid NOT NULL REFERENCES app.invoice_lines(id) ON DELETE RESTRICT,
            category_snapshot text NOT NULL CHECK (length(category_snapshot) BETWEEN 1 AND 100),
            original_amount_usd_cents bigint NOT NULL CHECK (original_amount_usd_cents BETWEEN 0 AND 9000000000000000),
            adjustment_net_usd_cents bigint NOT NULL
                CHECK (adjustment_net_usd_cents BETWEEN -9000000000000000 AND 9000000000000000),
            payment_allocated_usd_cents bigint NOT NULL
                CHECK (payment_allocated_usd_cents BETWEEN 0 AND 9000000000000000),
            credit_applied_usd_cents bigint NOT NULL CHECK (credit_applied_usd_cents BETWEEN 0 AND 9000000000000000),
            deposit_applied_usd_cents bigint NOT NULL CHECK (deposit_applied_usd_cents BETWEEN 0 AND 9000000000000000),
            closing_outstanding_usd_cents bigint NOT NULL
                CHECK (closing_outstanding_usd_cents BETWEEN 0 AND 9000000000000000),
            -- DB-DER-001: what a line still owes.
            CONSTRAINT settlement_invoice_line_items_reconcile CHECK (
                closing_outstanding_usd_cents::numeric=original_amount_usd_cents::numeric+adjustment_net_usd_cents
                    -payment_allocated_usd_cents-credit_applied_usd_cents-deposit_applied_usd_cents),
            CONSTRAINT settlement_invoice_line_items_once UNIQUE (settlement_invoice_item_id,invoice_line_id)
        );
        CREATE INDEX settlement_invoice_line_items_line_idx ON app.settlement_invoice_line_items(invoice_line_id);
        COMMENT ON TABLE app.settlement_invoice_line_items IS
            'Append-only Final Settlement closure snapshot of each Invoice line (DB-SETTLE-006)';

        -- Each snapshot row matches its Settlement Lease and the current derived values (DB-DER-001),
        -- and is written only while its Settlement is still open (the confirm closes it after).
        CREATE FUNCTION app.validate_settlement_closure_item()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_settlement app.final_settlements%ROWTYPE; v_line app.invoice_lines%ROWTYPE;
            v_item app.settlement_invoice_items%ROWTYPE; v_lease uuid; v_status text; v_owed bigint;
        BEGIN
            IF TG_TABLE_NAME='settlement_invoice_line_items' THEN
                SELECT * INTO v_item FROM app.settlement_invoice_items WHERE id=NEW.settlement_invoice_item_id;
                SELECT * INTO v_settlement FROM app.final_settlements WHERE id=v_item.final_settlement_id;
            ELSE
                SELECT * INTO v_settlement FROM app.final_settlements WHERE id=NEW.final_settlement_id;
            END IF;
            IF v_settlement.id IS NULL OR v_settlement.closed_at IS NOT NULL THEN
                RAISE EXCEPTION 'Closure snapshots are written only while the Final Settlement closes'
                    USING ERRCODE='55000'; END IF;
            IF TG_TABLE_NAME='settlement_invoice_items' THEN
                SELECT invoice.lease_id,invoice.status INTO v_lease,v_status FROM app.invoices invoice
                WHERE invoice.id=NEW.invoice_id;
                SELECT COALESCE(sum(app.invoice_line_outstanding(line.id)),0) INTO v_owed
                FROM app.invoice_lines line WHERE line.invoice_id=NEW.invoice_id;
                IF v_lease IS DISTINCT FROM v_settlement.lease_id OR v_status NOT IN ('UNPAID','PARTIALLY_PAID','PAID')
                    OR NEW.outstanding_at_inclusion_usd_cents IS DISTINCT FROM v_owed
                    OR NEW.included_at<v_settlement.started_at OR NEW.included_at>clock_timestamp()+interval '5 seconds'
                THEN RAISE EXCEPTION 'A Settlement Invoice snapshot must match an issued Invoice of the Settlement Lease'
                    USING ERRCODE='23514'; END IF;
            ELSIF TG_TABLE_NAME='settlement_late_payment_charge_items' THEN
                SELECT invoice.lease_id INTO v_lease FROM app.late_payment_charges charge
                JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                WHERE charge.id=NEW.late_payment_charge_id;
                SELECT position.remaining_balance_usd_cents INTO v_owed
                FROM app.late_payment_charge_financial_position position
                WHERE position.late_payment_charge_id=NEW.late_payment_charge_id;
                IF v_lease IS DISTINCT FROM v_settlement.lease_id
                    OR NEW.outstanding_at_inclusion_usd_cents IS DISTINCT FROM v_owed
                    OR NEW.included_at<v_settlement.started_at OR NEW.included_at>clock_timestamp()+interval '5 seconds'
                THEN RAISE EXCEPTION 'A Settlement Late-payment Charge snapshot must match a Charge of the Settlement Lease'
                    USING ERRCODE='23514'; END IF;
            ELSE
                SELECT * INTO v_line FROM app.invoice_lines WHERE id=NEW.invoice_line_id;
                IF v_line.invoice_id IS DISTINCT FROM v_item.invoice_id
                    OR NEW.category_snapshot IS DISTINCT FROM v_line.category
                    OR NEW.original_amount_usd_cents IS DISTINCT FROM v_line.amount_usd_cents
                    OR NEW.adjustment_net_usd_cents IS DISTINCT FROM
                        app.invoice_adjusted_line_obligation(v_line.id)-v_line.amount_usd_cents
                    OR NEW.payment_allocated_usd_cents IS DISTINCT FROM app.invoice_line_payment_value_at(v_line.id,'infinity')
                    OR NEW.credit_applied_usd_cents IS DISTINCT FROM app.invoice_line_credit_value_at(v_line.id,'infinity')
                    OR NEW.deposit_applied_usd_cents IS DISTINCT FROM app.invoice_line_deposit_value_at(v_line.id,'infinity')
                    OR NEW.closing_outstanding_usd_cents IS DISTINCT FROM app.invoice_line_outstanding(v_line.id)
                THEN RAISE EXCEPTION 'A Settlement Invoice line snapshot must match its line (DB-DER-001)'
                    USING ERRCODE='23514'; END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER settlement_invoice_items_validate BEFORE INSERT ON app.settlement_invoice_items
            FOR EACH ROW EXECUTE FUNCTION app.validate_settlement_closure_item();
        CREATE TRIGGER settlement_late_payment_charge_items_validate BEFORE INSERT
            ON app.settlement_late_payment_charge_items
            FOR EACH ROW EXECUTE FUNCTION app.validate_settlement_closure_item();
        CREATE TRIGGER settlement_invoice_line_items_validate BEFORE INSERT ON app.settlement_invoice_line_items
            FOR EACH ROW EXECUTE FUNCTION app.validate_settlement_closure_item();

        -- At commit (DB-SETTLE-006 deferred closure validation): the Settlement is closed, its
        -- snapshot covers every issued, non-VOID Invoice of the Lease with each of its lines and
        -- every Late-payment Charge of the Lease's Invoices, each Invoice snapshot is the sum of its
        -- line snapshots, and together they are the closing balance.
        CREATE FUNCTION app.assert_settlement_closure_reconciled()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_settlement app.final_settlements%ROWTYPE; v_total numeric;
        BEGIN
            SELECT * INTO v_settlement FROM app.final_settlements WHERE id=NEW.final_settlement_id;
            SELECT COALESCE((SELECT sum(item.outstanding_at_inclusion_usd_cents) FROM app.settlement_invoice_items item
                    WHERE item.final_settlement_id=v_settlement.id),0)
                +COALESCE((SELECT sum(item.outstanding_at_inclusion_usd_cents)
                    FROM app.settlement_late_payment_charge_items item
                    WHERE item.final_settlement_id=v_settlement.id),0)
            INTO v_total;
            IF v_settlement.closed_at IS NULL
                OR v_total IS DISTINCT FROM v_settlement.closing_balance_due_usd_cents::numeric
                OR EXISTS(SELECT 1 FROM app.invoices invoice
                    WHERE invoice.lease_id=v_settlement.lease_id AND invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID')
                      AND NOT EXISTS(SELECT 1 FROM app.settlement_invoice_items item
                          WHERE item.final_settlement_id=v_settlement.id AND item.invoice_id=invoice.id))
                OR EXISTS(SELECT 1 FROM app.late_payment_charges charge
                    JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                    WHERE invoice.lease_id=v_settlement.lease_id
                      AND NOT EXISTS(SELECT 1 FROM app.settlement_late_payment_charge_items item
                          WHERE item.final_settlement_id=v_settlement.id AND item.late_payment_charge_id=charge.id))
                OR EXISTS(SELECT 1 FROM app.settlement_invoice_items item
                    WHERE item.final_settlement_id=v_settlement.id
                      AND (item.outstanding_at_inclusion_usd_cents::numeric IS DISTINCT FROM (
                              SELECT COALESCE(sum(line_item.closing_outstanding_usd_cents),0)
                              FROM app.settlement_invoice_line_items line_item
                              WHERE line_item.settlement_invoice_item_id=item.id)
                          OR EXISTS(SELECT 1 FROM app.invoice_lines line WHERE line.invoice_id=item.invoice_id
                              AND NOT EXISTS(SELECT 1 FROM app.settlement_invoice_line_items line_item
                                  WHERE line_item.settlement_invoice_item_id=item.id
                                    AND line_item.invoice_line_id=line.id))))
            THEN RAISE EXCEPTION 'Final Settlement closure snapshots must reconcile to its closing balance'
                USING ERRCODE='23514'; END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER settlement_invoice_items_reconciled AFTER INSERT
            ON app.settlement_invoice_items DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION app.assert_settlement_closure_reconciled();
        CREATE CONSTRAINT TRIGGER settlement_late_payment_charge_items_reconciled AFTER INSERT
            ON app.settlement_late_payment_charge_items DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION app.assert_settlement_closure_reconciled();

        CREATE FUNCTION app.reject_settlement_closure_item_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Final Settlement closure snapshots are append-only' USING ERRCODE='55000';
        END $$;
        CREATE TRIGGER settlement_invoice_items_immutable BEFORE UPDATE OR DELETE ON app.settlement_invoice_items
            FOR EACH ROW EXECUTE FUNCTION app.reject_settlement_closure_item_mutation();
        CREATE TRIGGER settlement_invoice_items_no_truncate BEFORE TRUNCATE ON app.settlement_invoice_items
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_settlement_closure_item_mutation();
        CREATE TRIGGER settlement_late_payment_charge_items_immutable BEFORE UPDATE OR DELETE
            ON app.settlement_late_payment_charge_items
            FOR EACH ROW EXECUTE FUNCTION app.reject_settlement_closure_item_mutation();
        CREATE TRIGGER settlement_late_payment_charge_items_no_truncate BEFORE TRUNCATE
            ON app.settlement_late_payment_charge_items
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_settlement_closure_item_mutation();
        CREATE TRIGGER settlement_invoice_line_items_immutable BEFORE UPDATE OR DELETE
            ON app.settlement_invoice_line_items
            FOR EACH ROW EXECUTE FUNCTION app.reject_settlement_closure_item_mutation();
        CREATE TRIGGER settlement_invoice_line_items_no_truncate BEFORE TRUNCATE ON app.settlement_invoice_line_items
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_settlement_closure_item_mutation();

        -- A financial.approve holder confirms a pending FINAL_SETTLEMENT draft and closes its
        -- Settlement in one transaction (BR-SETTLE-007 to 009, 012, 015, 016; BR-AUTH-010; DL-032).
        -- Refusals: an unknown Property, draft or Settlement P0002/P4501; an inactive or missing
        -- approver P4506 or 42501; business state (a blocking issue, a plan the Settlement no longer
        -- allows, a decided draft, a closed Settlement, a waiting draft) 55000; a draft whose
        -- sources changed P5S02 (stale; it stays pending); a writer that finds a step no longer
        -- matching 23514, 23505 or the Credit proposal codes; a lock that cannot be taken 55P03 or
        -- 40P01. Nothing is written unless everything succeeds.
        CREATE FUNCTION app.confirm_final_settlement_draft(p_property uuid,p_actor uuid,p_draft uuid,
            p_authorization text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
            v_lease app.leases%ROWTYPE; v_move_out app.physical_move_out_events%ROWTYPE;
            v_settlement_id uuid; v_steps jsonb; v_plan jsonb; v_result jsonb; v_expected jsonb;
            v_digest text; v_item jsonb; v_position bigint; v_order integer:=0; v_id uuid; v_flag boolean;
            v_credits uuid[]; v_target_charges uuid[]; v_target_invoices uuid[]; v_credit_invoices uuid[];
            v_credit_ids uuid[]:='{}'; v_application_ids uuid[]:='{}'; v_refund_ids uuid[]:='{}';
            v_current bigint; v_outcome jsonb; v_closing bigint; v_at timestamptz; v_item_id uuid;
            v_reason text; v_snapshot jsonb;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property,p_actor);
            -- BR-AUTH-010: a person confirms; an inactive approver is refused above (P4506).
            IF NOT EXISTS(SELECT 1 FROM app.actor_identities identity
                WHERE identity.actor_id=p_actor AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'A Final Settlement is confirmed only by a human approver' USING ERRCODE='42501'; END IF;
            IF p_authorization IS DISTINCT FROM 'financial.approve' THEN
                RAISE EXCEPTION 'Only financial.approve may confirm a Final Settlement draft' USING ERRCODE='42501'; END IF;
            IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' THEN
                RAISE EXCEPTION 'Final Settlement confirmation is invalid' USING ERRCODE='22023'; END IF;
            -- The serialization of every decision on this draft, then the replay of an exact repeat.
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
            SELECT draft.* INTO v_draft FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
            WHERE draft.id=p_draft AND draft.property_id=p_property AND draft.kind='FINAL_SETTLEMENT'
              AND decision.decision='CONFIRMED' AND decision.decided_by=p_actor;
            IF FOUND THEN
                v_settlement_id:=(v_draft.payload->>'final_settlement_id')::uuid;
                RETURN jsonb_build_object('draft',app.financial_draft_json(v_draft),
                    'settlement',app.final_settlement_json(v_settlement_id),
                    'result',(SELECT decision.result FROM app.financial_draft_decisions decision
                        WHERE decision.draft_id=p_draft));
            END IF;
            SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
            IF NOT FOUND OR v_draft.kind<>'FINAL_SETTLEMENT' OR v_draft.prepare_capability<>'final_settlements.prepare'
                OR v_draft.payload->>'variant' IS DISTINCT FROM 'FINAL_SETTLEMENT'
            THEN RAISE EXCEPTION 'Final Settlement draft was not found' USING ERRCODE='P0002'; END IF;
            IF EXISTS(SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=p_draft) THEN
                RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE='55000'; END IF;
            v_settlement_id:=app.final_settlement_plan_id(v_draft.payload->'final_settlement_id')::uuid;
            SELECT * INTO v_settlement FROM app.final_settlements
            WHERE id=v_settlement_id AND property_id=p_property;
            IF NOT FOUND THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
            -- Plan note 15: the checks below rely on READ COMMITTED (each statement sees the commits
            -- the locks waited for).
            IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
                RAISE EXCEPTION 'A Final Settlement is confirmed at READ COMMITTED' USING ERRCODE='55000'; END IF;
            v_steps:=v_draft.payload->'steps';
            IF jsonb_typeof(v_steps) IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'Final Settlement draft was not found' USING ERRCODE='P0002'; END IF;

            -- Lock order (plan notes 7 and 14, amended by the 8e-2 notes; the Lease row position from
            -- the 8e-2 round-3 note): the Settlement draft lock of the recorder; the Lease row (the
            -- Lease-first writers: termination and move-out commands, the start of a Settlement, the
            -- unpaid-Initial and hand-back resolutions; and a new charge whose guard ran before the
            -- Settlement started waits through its key lock on the Lease); the Payments, then the
            -- Credits, of the Customer Credit steps (Payment before Invoice, as the one-call Credit and
            -- allocation writers); the Late-payment Charges, then the Invoices, of the Lease in id
            -- order (a Charge before its source Invoice), FOR UPDATE where a step pays it (with the
            -- lines of a Credit step's Invoice), FOR NO KEY UPDATE otherwise; the Settlement row; then
            -- for each Deposit of the Lease in id order its draft lock and its row. The Settlement
            -- writers then take nothing stronger than these. A detected deadlock (40P01) is a conflict.
            PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement_id::text,0));
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE;
            SELECT COALESCE(array_agg(DISTINCT app.final_settlement_plan_id(step->'customer_credit_id')::uuid),'{}')
            INTO v_credits FROM jsonb_array_elements(v_steps) step WHERE step->>'kind'='CUSTOMER_CREDIT';
            SELECT COALESCE(array_agg(DISTINCT app.final_settlement_plan_id(step->'target_id')::uuid),'{}')
            INTO v_target_charges FROM jsonb_array_elements(v_steps) step
            WHERE step->>'kind'<>'DEPOSIT_REFUNDS' AND step->>'target_kind'='LATE_PAYMENT_CHARGE';
            SELECT COALESCE(array_agg(DISTINCT line.invoice_id),'{}') INTO v_target_invoices
            FROM jsonb_array_elements(v_steps) step
            JOIN app.invoice_lines line ON line.id=app.final_settlement_plan_id(step->'target_id')::uuid
            WHERE step->>'kind'<>'DEPOSIT_REFUNDS' AND step->>'target_kind'='INVOICE_LINE';
            SELECT COALESCE(array_agg(DISTINCT line.invoice_id),'{}') INTO v_credit_invoices
            FROM jsonb_array_elements(v_steps) step
            JOIN app.invoice_lines line ON line.id=app.final_settlement_plan_id(step->'target_id')::uuid
            WHERE step->>'kind'='CUSTOMER_CREDIT' AND step->>'target_kind'='INVOICE_LINE';
            v_target_invoices:=v_target_invoices||COALESCE((SELECT array_agg(charge.source_invoice_id)
                FROM app.late_payment_charges charge WHERE charge.id=ANY(v_target_charges)),'{}');
            FOR v_id IN SELECT DISTINCT credit.source_payment_id FROM app.customer_credits credit
                WHERE credit.id=ANY(v_credits) ORDER BY 1
            LOOP
                PERFORM app.serialize_payment_state(v_id);
                PERFORM 1 FROM app.payments WHERE id=v_id FOR UPDATE;
            END LOOP;
            PERFORM 1 FROM app.customer_credits WHERE id=ANY(v_credits) ORDER BY id FOR UPDATE;
            FOR v_id,v_flag IN SELECT charge.id,charge.id=ANY(v_target_charges) FROM app.late_payment_charges charge
                JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                WHERE invoice.lease_id=v_lease.id ORDER BY charge.id
            LOOP
                IF v_flag THEN PERFORM 1 FROM app.late_payment_charges WHERE id=v_id FOR UPDATE;
                ELSE PERFORM 1 FROM app.late_payment_charges WHERE id=v_id FOR NO KEY UPDATE; END IF;
            END LOOP;
            FOR v_id,v_flag IN SELECT invoice.id,invoice.id=ANY(v_target_invoices) FROM app.invoices invoice
                WHERE invoice.lease_id=v_lease.id ORDER BY invoice.id
            LOOP
                IF v_flag THEN
                    PERFORM 1 FROM app.invoices WHERE id=v_id FOR UPDATE;
                    IF v_id=ANY(v_credit_invoices) THEN
                        PERFORM 1 FROM app.invoice_lines WHERE invoice_id=v_id ORDER BY id FOR UPDATE;
                    END IF;
                ELSE PERFORM 1 FROM app.invoices WHERE id=v_id FOR NO KEY UPDATE; END IF;
            END LOOP;
            SELECT * INTO STRICT v_settlement FROM app.final_settlements WHERE id=v_settlement_id FOR UPDATE;
            IF v_settlement.closed_at IS NOT NULL THEN
                RAISE EXCEPTION 'A closed Final Settlement is never reopened or changed' USING ERRCODE='55000'; END IF;
            FOR v_id IN SELECT deposit.id FROM app.deposits deposit WHERE deposit.lease_id=v_lease.id ORDER BY deposit.id
            LOOP
                PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || v_id::text,0));
                PERFORM app.serialize_deposit_state(v_id);
            END LOOP;

            -- Plan note 1: the current physical move-out at the confirm.
            SELECT count(*) INTO v_current FROM app.physical_move_out_events move_out
            WHERE move_out.lease_id=v_lease.id AND NOT EXISTS(
                SELECT 1 FROM app.physical_move_out_events later WHERE later.supersedes_event_id=move_out.id);
            IF v_current>1 THEN
                RAISE EXCEPTION 'The current move-out record is ambiguous' USING ERRCODE='55000'; END IF;
            SELECT move_out.* INTO v_move_out FROM app.physical_move_out_events move_out
            WHERE move_out.lease_id=v_lease.id AND NOT EXISTS(
                SELECT 1 FROM app.physical_move_out_events later WHERE later.supersedes_event_id=move_out.id);

            -- Plan notes 6, 8 and 15, owner answers 2 and 3 to Q-2026-10-06-33: under every lock, the
            -- sources still have the digest the draft recorded, and the plan check of sub-slice 8c
            -- (every preview blocking issue, pending drafts and RENT_PERIOD_NOT_BILLED and
            -- INVOICE_DRAFT_NOT_ISSUED included; the strict DL-032 order; the three cases of a kept
            -- Deposit) still accepts the draft with the same result. Otherwise the draft is stale
            -- and stays pending.
            v_digest:='final-settlement:' || encode(sha256(convert_to(
                app.final_settlement_source_state(p_property,v_settlement_id)::text,'UTF8')),'hex');
            IF v_digest IS DISTINCT FROM v_draft.source_revision THEN
                RAISE EXCEPTION 'The Final Settlement draft is stale; its sources changed' USING ERRCODE='P5S02'; END IF;
            v_plan:=jsonb_build_object('steps',v_steps,'pet_remainder',v_draft.payload->'pet_remainder');
            v_result:=app.final_settlement_plan_result(p_property,p_actor,v_settlement_id,v_plan);
            v_expected:=v_draft.payload-'variant'-'final_settlement_id'-'steps'-'pet_remainder';
            IF v_result->>'source_revision' IS DISTINCT FROM v_draft.source_revision
                OR (v_result-'source_revision') IS DISTINCT FROM v_expected
            THEN RAISE EXCEPTION 'The Final Settlement draft is stale; its sources changed' USING ERRCODE='P5S02'; END IF;
            v_closing:=(v_result->>'closing_balance_usd_cents')::bigint;

            -- The ids every step will write, so the decision records them first (plan note 12).
            SELECT COALESCE(array_agg(app.final_settlement_credit_application_id(p_draft,step.ordinality::integer)
                    ORDER BY step.ordinality) FILTER (WHERE step.value->>'kind'='CUSTOMER_CREDIT'),'{}'),
                COALESCE(array_agg(app.final_settlement_deposit_application_id(p_draft,step.ordinality::integer)
                    ORDER BY step.ordinality) FILTER (WHERE step.value->>'kind' IN
                        ('PET_DEPOSIT_PET_DAMAGE','SECURITY_DEPOSIT','PET_DEPOSIT_REMAINDER')),'{}'),
                COALESCE(array_agg(app.final_settlement_refund_id(p_draft,
                        app.final_settlement_plan_id(step.value->'deposit_id')::uuid)
                    ORDER BY app.final_settlement_plan_id(step.value->'deposit_id')::uuid)
                    FILTER (WHERE step.value->>'kind'='DEPOSIT_REFUNDS'),'{}')
            INTO v_credit_ids,v_application_ids,v_refund_ids
            FROM jsonb_array_elements(v_steps) WITH ORDINALITY AS step(value,ordinality);
            v_outcome:=jsonb_build_object('final_settlement_id',v_settlement_id,
                'closing_balance_usd_cents',v_closing,'closing_balances',v_result->'closing_balances',
                'source_revision',v_result->'source_revision',
                'credit_application_ids',to_jsonb(v_credit_ids),
                'deposit_application_ids',to_jsonb(v_application_ids),
                'refund_ids',to_jsonb(v_refund_ids));
            -- The decision first: the Settlement writers commit only with it (8d, 8e-2), and its
            -- trigger refuses while a receipt reversal draft of a Deposit in the draft waits (8r).
            PERFORM app.confirm_financial_draft_record(p_property,p_actor,p_draft,'FINAL_SETTLEMENT',
                v_outcome,'financial.approve');

            -- DL-032 step 2: each Customer Credit step, in the draft's order (8e-2 writer).
            FOR v_item,v_position IN SELECT step.value,step.ordinality
                FROM jsonb_array_elements(v_steps) WITH ORDINALITY AS step(value,ordinality)
                WHERE step.value->>'kind'='CUSTOMER_CREDIT' ORDER BY step.ordinality
            LOOP
                PERFORM app.post_final_settlement_credit_application(p_property,p_actor,v_settlement_id,
                    p_draft,v_position::integer);
            END LOOP;
            -- DL-032 steps 3 to 5: each Deposit application, in the draft's order (8a writer); the
            -- remaining Pet Deposit records the staff reason of its step 5 decision.
            FOR v_item,v_position IN SELECT step.value,step.ordinality
                FROM jsonb_array_elements(v_steps) WITH ORDINALITY AS step(value,ordinality)
                WHERE step.value->>'kind' IN ('PET_DEPOSIT_PET_DAMAGE','SECURITY_DEPOSIT','PET_DEPOSIT_REMAINDER')
                ORDER BY step.ordinality
            LOOP
                v_order:=v_order+1;
                v_reason:=v_draft.reason;
                IF v_item->>'kind'='PET_DEPOSIT_REMAINDER' THEN
                    v_reason:=v_draft.payload->'pet_remainder'->>'staff_reason';
                END IF;
                PERFORM app.post_deposit_application(p_property,p_actor,v_settlement_id,
                    app.final_settlement_deposit_application_id(p_draft,v_position::integer),
                    app.final_settlement_plan_id(v_item->'deposit_id')::uuid,
                    CASE v_item->>'kind' WHEN 'PET_DEPOSIT_PET_DAMAGE' THEN 'PET_RELATED_FIRST'
                        WHEN 'SECURITY_DEPOSIT' THEN 'SECURITY_EXPLICIT' ELSE 'PET_REMAINDER_EXPLICIT' END,
                    v_item->>'target_kind',app.final_settlement_plan_id(v_item->'target_id')::uuid,
                    (v_item->>'amount_usd_cents')::bigint,v_order,v_reason);
            END LOOP;
            -- DL-032 step 7: the Refunds, in Deposit id order (8d writer).
            FOR v_item IN SELECT step.value FROM jsonb_array_elements(v_steps) step
                WHERE step.value->>'kind'='DEPOSIT_REFUNDS'
                ORDER BY app.final_settlement_plan_id(step.value->'deposit_id')::uuid
            LOOP
                PERFORM app.post_final_settlement_deposit_refund(p_property,p_actor,v_settlement_id,p_draft,
                    app.final_settlement_refund_id(p_draft,app.final_settlement_plan_id(v_item->'deposit_id')::uuid),
                    app.final_settlement_plan_id(v_item->'deposit_id')::uuid,(v_item->>'amount_usd_cents')::bigint,
                    app.final_settlement_plan_id(v_item->'recipient_customer_id')::uuid,
                    app.final_settlement_plan_id(v_item->'refund_method_id')::uuid,v_item->>'reference_note',
                    v_item->>'signer_agreement',v_draft.reason);
            END LOOP;
            -- Every writer's own checks now, before the closure is written (plan note 17).
            SET CONSTRAINTS ALL IMMEDIATE;

            -- The closure checks (8e-2 security note): exactly the records the draft names.
            IF (SELECT count(*) FROM app.customer_credit_applications application
                    WHERE application.final_settlement_id=v_settlement_id)<>cardinality(v_credit_ids)
                OR EXISTS(SELECT 1 FROM unnest(v_credit_ids) expected(id) WHERE NOT EXISTS(
                    SELECT 1 FROM app.customer_credit_applications application
                    WHERE application.id=expected.id AND application.final_settlement_id=v_settlement_id))
                OR (SELECT count(*) FROM app.deposit_applications application
                    WHERE application.final_settlement_id=v_settlement_id)<>cardinality(v_application_ids)
                OR EXISTS(SELECT 1 FROM unnest(v_application_ids) expected(id) WHERE NOT EXISTS(
                    SELECT 1 FROM app.deposit_applications application
                    WHERE application.id=expected.id AND application.final_settlement_id=v_settlement_id))
                OR (SELECT count(*) FROM app.final_settlement_refund_details detail
                    WHERE detail.final_settlement_id=v_settlement_id)<>cardinality(v_refund_ids)
                OR EXISTS(SELECT 1 FROM unnest(v_refund_ids) expected(id) WHERE NOT EXISTS(
                    SELECT 1 FROM app.final_settlement_refund_details detail
                    WHERE detail.refund_id=expected.id AND detail.final_settlement_id=v_settlement_id))
                -- BR-SETTLE-008: every Deposit that follows DL-032 ends with nothing held.
                OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(v_result->'deposit_ids') deposit(id)
                    WHERE app.deposit_held_value_at(deposit.id::uuid,'infinity')<>0)
            THEN RAISE EXCEPTION 'The Final Settlement closes only with exactly the applications and Refunds of its draft'
                USING ERRCODE='23514'; END IF;

            -- The closure snapshots (DB-SETTLE-002, 004, 006), checked again at commit.
            SET CONSTRAINTS app.settlement_invoice_items_reconciled,
                app.settlement_late_payment_charge_items_reconciled DEFERRED;
            v_at:=clock_timestamp();
            FOR v_id IN SELECT invoice.id FROM app.invoices invoice
                WHERE invoice.lease_id=v_lease.id AND invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID')
                ORDER BY invoice.id
            LOOP
                v_item_id:=gen_random_uuid();
                INSERT INTO app.settlement_invoice_items(final_settlement_id,invoice_id,id,
                    outstanding_at_inclusion_usd_cents,included_at,included_by)
                SELECT v_settlement_id,v_id,v_item_id,COALESCE(sum(app.invoice_line_outstanding(line.id)),0),v_at,p_actor
                FROM app.invoice_lines line WHERE line.invoice_id=v_id;
                INSERT INTO app.settlement_invoice_line_items(id,settlement_invoice_item_id,invoice_line_id,
                    category_snapshot,original_amount_usd_cents,adjustment_net_usd_cents,
                    payment_allocated_usd_cents,credit_applied_usd_cents,deposit_applied_usd_cents,
                    closing_outstanding_usd_cents)
                SELECT gen_random_uuid(),v_item_id,line.id,line.category,line.amount_usd_cents,
                    app.invoice_adjusted_line_obligation(line.id)-line.amount_usd_cents,
                    app.invoice_line_payment_value_at(line.id,'infinity'),
                    app.invoice_line_credit_value_at(line.id,'infinity'),
                    app.invoice_line_deposit_value_at(line.id,'infinity'),
                    app.invoice_line_outstanding(line.id)
                FROM app.invoice_lines line WHERE line.invoice_id=v_id ORDER BY line.line_sequence,line.id;
            END LOOP;
            INSERT INTO app.settlement_late_payment_charge_items(final_settlement_id,late_payment_charge_id,
                outstanding_at_inclusion_usd_cents,included_at,included_by)
            SELECT v_settlement_id,charge.id,position.remaining_balance_usd_cents,v_at,p_actor
            FROM app.late_payment_charges charge
            JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
            JOIN app.late_payment_charge_financial_position position ON position.late_payment_charge_id=charge.id
            WHERE invoice.lease_id=v_lease.id ORDER BY charge.id;
            -- BR-SETTLE-007 and BR-SETTLE-016: what stays open is the closing balance; it stays on the
            -- ledger of the person named on each obligation (nothing is written off).
            IF COALESCE((SELECT sum(item.outstanding_at_inclusion_usd_cents) FROM app.settlement_invoice_items item
                    WHERE item.final_settlement_id=v_settlement_id),0)
                +COALESCE((SELECT sum(item.outstanding_at_inclusion_usd_cents)
                    FROM app.settlement_late_payment_charge_items item
                    WHERE item.final_settlement_id=v_settlement_id),0)<>v_closing
            THEN RAISE EXCEPTION 'Final Settlement closure snapshots must reconcile to its closing balance'
                USING ERRCODE='23514'; END IF;

            -- The single closure (BR-SETTLE-012): never reopened or changed again.
            v_snapshot:=v_outcome||jsonb_build_object('draft_id',p_draft,'prepared_by',v_draft.prepared_by,
                'termination_ground',v_result->'termination_ground',
                'pet_remainder_chosen_by',v_result->'pet_remainder_chosen_by',
                'deposit_ids',v_result->'deposit_ids','open_total_usd_cents',v_result->'open_total_usd_cents',
                'move_out_event_id',v_move_out.id,'move_out_date',v_move_out.actual_move_out_date);
            v_at:=clock_timestamp();
            UPDATE app.final_settlements SET closed_at=v_at,closed_by=p_actor,source_snapshot=v_snapshot,
                closing_balance_due_usd_cents=v_closing
            WHERE id=v_settlement_id;
            -- One audit event names the draft and every record the Settlement wrote; the existing
            -- Credit, Deposit application and Refund events stay as they are.
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,resulting_state,correlation_id,source,outcome,
                customer_id,lease_id)
            VALUES(gen_random_uuid(),v_at,(v_at AT TIME ZONE 'Asia/Phnom_Penh')::date,p_actor,
                'final_settlement.closed','final_settlement',v_settlement_id,v_draft.reason,'financial.approve',
                p_property,v_snapshot||jsonb_build_object('closed_at',v_at),p_draft,'API','SUCCESS',
                v_lease.primary_tenant_id,v_lease.id);
            -- Every deferred check fires here, inside the confirm; the transaction keeps this mode,
            -- which the service ends at once with its commit.
            SET CONSTRAINTS ALL IMMEDIATE;
            RETURN jsonb_build_object('draft',app.financial_draft_json(v_draft),
                'settlement',app.final_settlement_json(v_settlement_id),'result',v_outcome);
        END $$;
    """)
    _patch(PREVIEW, ((RENT_BEFORE, RENT_AFTER),))
    _patch(GUARD, ((GUARD_BEFORE, GUARD_AFTER),))
    for table in (
        "app.settlement_invoice_items",
        "app.settlement_late_payment_charge_items",
        "app.settlement_invoice_line_items",
    ):
        op.execute(
            f"REVOKE ALL ON TABLE {table} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in (CONFIRM, *INTERNAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {CONFIRM} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Final Settlement confirm migration is forward-only")
