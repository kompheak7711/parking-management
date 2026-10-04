# ruff: noqa: E501
"""Wrong-Unit Payment move drafts (BR-PAY-042, BR-AUTH-010; V1-056 slice 7).

Owner answers to Q-2026-10-05-16 and Q-2026-10-05-17 (2026-10-05):
- Staff holding payments.allocations.reverse record a PAYMENT_MOVE draft naming the wrong
  Invoice allocation, the correct Invoice on another Unit, a reason and the two Customers'
  acknowledgements (who, the date and how, as text). It has no financial effect until a
  financial.approve holder confirms it.
- Confirmation reverses the wrong allocation (unless the one-call reversal already did) and
  allocates the same Payment to the correct Invoice in one transaction. The new allocation has
  its own basis WRONG_UNIT_MOVE, exempt from the payer check (BR-PAY-025) and the third-party
  intent check (BR-PAY-026); only a confirmed move, or a credit Adjustment's re-post of such an
  allocation, may create one. The Payment row and its Receipt never change.
- The move is blocked while the Payment has Customer Credit that is not reversed or a Refund that
  is not fully returned. On the correct Invoice the amount follows the within-Invoice default
  order (BR-PAY-036). Late-payment and Rent nonpayment rules are unchanged.
- A moved allocation is never reversed by the one-call reversal (Q-2026-10-05-17); it changes
  only through another move draft or a credit Adjustment on its Invoice.
- A Credit that a credit Adjustment released from a moved allocation is never reversed by the
  one-call Credit reversal unless the Payment is a normal Customer Payment and the Credit belongs to
  its payer (Q-2026-10-05-18, Q-2026-10-05-19): otherwise the value could return to the payer's
  Payment and reach another Customer without a draft. Such a Credit stays with its Customer: a
  Credit of a Customer other than the payer can only be applied to that Customer's obligations (its
  Refund to that Customer is planned for slice 9); a third-party payer's own Credit can still be
  refunded to the payer through a Refund draft.

Additive and relaxing: a new link table, functions and constraint triggers; the allocation basis
check gains WRONG_UNIT_MOVE, and the allocation source guard exempts that basis from the payer and
intent checks. The new reversal refusals apply only to WRONG_UNIT_MOVE allocations and to Credits
released from them, which did not exist before this migration. The allocation audit names the move
as its reason.
"""

from alembic import op
from sqlalchemy import text

revision = "20261020_85"
down_revision = "20261019_84"
branch_labels = None
depends_on = None

SOURCE = "app.payment_move_source(uuid,uuid,uuid)"
RECORD_DRAFT = "app.record_payment_move_draft(uuid,uuid,uuid,uuid,uuid,text,text,text,text)"
CONFIRM_DRAFT = "app.confirm_payment_move_draft(uuid,uuid,uuid,text)"
GUARDS = (
    "app.validate_payment_move()",
    "app.validate_payment_move_confirmed()",
    "app.validate_wrong_unit_move_allocation()",
    "app.validate_wrong_unit_move_reversal()",
    "app.reject_payment_move_mutation()",
    "app.validate_moved_credit_reversal()",
)
MOVE_REASON = "Wrong-Unit Payment move confirmed (BR-PAY-042)"

PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.validate_payment_allocation_source()",
        (
            (
                "            IF v_payment.payment_scope_kind='NORMAL_CUSTOMER' THEN\n",
                "            IF NEW.between_invoice_basis='WRONG_UNIT_MOVE' THEN\n"
                "                -- BR-PAY-042: a confirmed wrong-Unit move (or its credit-Adjustment\n"
                "                -- re-post) is exempt from the payer and intent checks; a deferred\n"
                "                -- check proves its link to the move.\n"
                "                IF NEW.target_kind<>'INVOICE' THEN\n"
                "                    RAISE EXCEPTION 'A wrong-Unit move targets an Invoice' USING ERRCODE='23514';\n"
                "                END IF;\n"
                "            ELSIF v_payment.payment_scope_kind='NORMAL_CUSTOMER' THEN\n",
            ),
            (
                "            IF (v_payment.identified_invoice_id IS NOT NULL\n"
                "                    AND v_target_invoice IS DISTINCT FROM v_payment.identified_invoice_id)\n"
                "                OR (v_payment.identified_late_payment_charge_id IS NOT NULL\n"
                "                    AND NEW.late_payment_charge_id IS DISTINCT FROM v_payment.identified_late_payment_charge_id)\n"
                "            THEN",
                "            IF NEW.between_invoice_basis<>'WRONG_UNIT_MOVE' AND ((v_payment.identified_invoice_id IS NOT NULL\n"
                "                    AND v_target_invoice IS DISTINCT FROM v_payment.identified_invoice_id)\n"
                "                OR (v_payment.identified_late_payment_charge_id IS NOT NULL\n"
                "                    AND NEW.late_payment_charge_id IS DISTINCT FROM v_payment.identified_late_payment_charge_id))\n"
                "            THEN",
            ),
        ),
    ),
    (
        "app.audit_payment_allocation_event()",
        (
            (
                "THEN 'Invoice adjustment credit excess' ELSE 'Explicitly confirmed allocation' END;",
                "THEN 'Invoice adjustment credit excess'\n"
                f"                    WHEN NEW.between_invoice_basis='WRONG_UNIT_MOVE' THEN '{MOVE_REASON}'\n"
                "                    ELSE 'Explicitly confirmed allocation' END;",
            ),
        ),
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
            raise RuntimeError(f"Payment move source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def _basis_check() -> str:
    names = (
        op.get_bind()
        .execute(
            text(
                "SELECT conname FROM pg_catalog.pg_constraint "
                "WHERE conrelid='app.payment_allocations'::regclass AND contype='c' "
                "AND pg_catalog.pg_get_constraintdef(oid) LIKE '%between_invoice_basis%' "
                "AND pg_catalog.pg_get_constraintdef(oid) LIKE '%DIRECT_LATE_PAYMENT_CHARGE%' "
                "AND pg_catalog.pg_get_constraintdef(oid) NOT LIKE '%proposal_batch_id%'"
            )
        )
        .scalars()
        .all()
    )
    if len(names) != 1:
        raise RuntimeError("Payment allocation basis constraint is not unique")
    return str(names[0])


def upgrade() -> None:
    basis = '"' + _basis_check().replace('"', '""') + '"'
    # Relaxing: one more allocation basis value.
    op.execute(f"""
        ALTER TABLE app.payment_allocations DROP CONSTRAINT {basis};
        ALTER TABLE app.payment_allocations ADD CONSTRAINT {basis} CHECK (between_invoice_basis IN (
            'FIFO_PROPOSAL','CUSTOMER_DESIGNATED','THIRD_PARTY_DESIGNATED',
            'DIRECT_LATE_PAYMENT_CHARGE','WRONG_UNIT_MOVE'));
    """)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    op.execute("""
        -- One row per confirmed move: the draft, the reversed wrong allocation and the new one.
        CREATE TABLE app.payment_moves (
            id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'::uuid),
            draft_id uuid NOT NULL UNIQUE REFERENCES app.financial_drafts(id) ON DELETE RESTRICT,
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            payment_id uuid NOT NULL REFERENCES app.payments(id) ON DELETE RESTRICT,
            source_allocation_id uuid NOT NULL UNIQUE
                REFERENCES app.payment_allocations(id) ON DELETE RESTRICT,
            source_reversal_id uuid NOT NULL UNIQUE
                REFERENCES app.payment_allocation_reversals(id) ON DELETE RESTRICT,
            source_reversed_by_move boolean NOT NULL,
            target_allocation_id uuid NOT NULL UNIQUE
                REFERENCES app.payment_allocations(id) ON DELETE RESTRICT,
            source_invoice_id uuid NOT NULL REFERENCES app.invoices(id) ON DELETE RESTRICT,
            target_invoice_id uuid NOT NULL REFERENCES app.invoices(id) ON DELETE RESTRICT,
            moved_usd_cents bigint NOT NULL CHECK (moved_usd_cents BETWEEN 1 AND 9000000000000000),
            source_acknowledgement text NOT NULL
                CHECK (source_acknowledgement=btrim(source_acknowledgement)
                    AND length(source_acknowledgement) BETWEEN 1 AND 2000),
            target_acknowledgement text NOT NULL
                CHECK (target_acknowledgement=btrim(target_acknowledgement)
                    AND length(target_acknowledgement) BETWEEN 1 AND 2000),
            confirmed_at timestamptz NOT NULL CHECK (isfinite(confirmed_at)),
            confirmed_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            CONSTRAINT payment_move_distinct CHECK (source_invoice_id<>target_invoice_id
                AND source_allocation_id<>target_allocation_id)
        );
        CREATE INDEX payment_moves_payment_idx ON app.payment_moves(payment_id,confirmed_at,id);
        CREATE FUNCTION app.reject_payment_move_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Payment moves are append-only' USING ERRCODE='55000';
        END $$;
        CREATE TRIGGER payment_moves_immutable BEFORE UPDATE OR DELETE ON app.payment_moves
            FOR EACH ROW EXECUTE FUNCTION app.reject_payment_move_mutation();
        CREATE TRIGGER payment_moves_no_truncate BEFORE TRUNCATE ON app.payment_moves
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_payment_move_mutation();

        -- The link must match its pending draft, the reversed wrong allocation and the new one.
        CREATE FUNCTION app.validate_payment_move()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE; v_source app.payment_allocations%ROWTYPE;
            v_target app.payment_allocations%ROWTYPE; v_reversal app.payment_allocation_reversals%ROWTYPE;
        BEGIN
            PERFORM app.assert_active_financial_actor(NEW.confirmed_by,NEW.property_id);
            SELECT * INTO v_draft FROM app.financial_drafts WHERE id=NEW.draft_id;
            SELECT * INTO v_source FROM app.payment_allocations WHERE id=NEW.source_allocation_id;
            SELECT * INTO v_target FROM app.payment_allocations WHERE id=NEW.target_allocation_id;
            SELECT * INTO v_reversal FROM app.payment_allocation_reversals WHERE id=NEW.source_reversal_id;
            IF v_draft.id IS NULL OR v_draft.kind<>'PAYMENT_MOVE' OR v_draft.property_id<>NEW.property_id
                OR v_draft.payload->>'variant' IS DISTINCT FROM 'WRONG_UNIT_MOVE'
                OR v_draft.payload->>'source_allocation_id' IS DISTINCT FROM NEW.source_allocation_id::text
                OR v_draft.payload->>'target_invoice_id' IS DISTINCT FROM NEW.target_invoice_id::text
                OR v_draft.payload->>'source_acknowledgement' IS DISTINCT FROM NEW.source_acknowledgement
                OR v_draft.payload->>'target_acknowledgement' IS DISTINCT FROM NEW.target_acknowledgement
                OR v_draft.payload->'source'->>'payment_id' IS DISTINCT FROM NEW.payment_id::text
                OR v_draft.payload->'source'->>'source_invoice_id' IS DISTINCT FROM NEW.source_invoice_id::text
                OR (v_draft.payload->'source'->>'moved_usd_cents')::bigint IS DISTINCT FROM NEW.moved_usd_cents
                OR (v_draft.payload->'source'->>'source_reversed')::boolean IS DISTINCT FROM NOT NEW.source_reversed_by_move
                OR EXISTS (SELECT 1 FROM app.financial_draft_decisions WHERE draft_id=NEW.draft_id)
                OR v_source.payment_id IS DISTINCT FROM NEW.payment_id OR v_source.target_kind<>'INVOICE'
                OR v_source.invoice_id IS DISTINCT FROM NEW.source_invoice_id
                OR v_reversal.payment_allocation_id IS DISTINCT FROM NEW.source_allocation_id
                OR (NEW.source_reversed_by_move AND v_reversal.actor_id IS DISTINCT FROM NEW.confirmed_by)
                OR v_target.payment_id IS DISTINCT FROM NEW.payment_id
                OR v_target.invoice_id IS DISTINCT FROM NEW.target_invoice_id
                OR v_target.between_invoice_basis IS DISTINCT FROM 'WRONG_UNIT_MOVE'
                OR v_target.amount_usd_cents IS DISTINCT FROM NEW.moved_usd_cents
                OR v_target.posted_by IS DISTINCT FROM NEW.confirmed_by
            THEN RAISE EXCEPTION 'Payment move does not match its draft' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER payment_moves_validate BEFORE INSERT ON app.payment_moves
            FOR EACH ROW EXECUTE FUNCTION app.validate_payment_move();

        -- At commit the move's draft carries the approver's CONFIRMED decision.
        CREATE FUNCTION app.validate_payment_move_confirmed()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM app.financial_draft_decisions decision
                WHERE decision.draft_id=NEW.draft_id AND decision.decision='CONFIRMED'
                  AND decision.decided_by=NEW.confirmed_by
                  AND decision.authorization_reference='financial.approve')
            THEN RAISE EXCEPTION 'A Payment move needs a confirmed draft' USING ERRCODE='23514'; END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER payment_moves_confirmed AFTER INSERT ON app.payment_moves
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION app.validate_payment_move_confirmed();

        -- Only a confirmed move, or a credit Adjustment's re-post of a moved allocation, may
        -- create a WRONG_UNIT_MOVE allocation.
        CREATE FUNCTION app.validate_wrong_unit_move_allocation()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM app.payment_moves move
                    WHERE move.target_allocation_id=NEW.id AND move.payment_id=NEW.payment_id
                      AND move.target_invoice_id=NEW.invoice_id)
                AND NOT EXISTS (SELECT 1 FROM app.invoice_credit_excess_releases release
                    JOIN app.payment_allocations prior ON prior.id=release.reversed_payment_allocation_id
                    WHERE release.replacement_payment_allocation_id=NEW.id
                      AND prior.between_invoice_basis='WRONG_UNIT_MOVE'
                      AND prior.payment_id=NEW.payment_id AND prior.invoice_id=NEW.invoice_id)
            THEN RAISE EXCEPTION 'A wrong-Unit move allocation needs a confirmed move draft'
                USING ERRCODE='23514'; END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER payment_allocations_wrong_unit_move AFTER INSERT
            ON app.payment_allocations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            WHEN (NEW.between_invoice_basis='WRONG_UNIT_MOVE')
            EXECUTE FUNCTION app.validate_wrong_unit_move_allocation();

        -- Q-2026-10-05-17: a moved allocation is reversed only by another move or by a credit
        -- Adjustment on its Invoice, never by the one-call reversal.
        CREATE FUNCTION app.validate_wrong_unit_move_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM app.payment_allocations allocation
                    WHERE allocation.id=NEW.payment_allocation_id
                      AND allocation.between_invoice_basis='WRONG_UNIT_MOVE')
                AND NOT EXISTS (SELECT 1 FROM app.payment_moves move
                    WHERE move.source_allocation_id=NEW.payment_allocation_id
                      AND move.source_reversal_id=NEW.id)
                AND NOT EXISTS (SELECT 1 FROM app.invoice_credit_excess_releases release
                    WHERE release.reversed_payment_allocation_id=NEW.payment_allocation_id)
            THEN RAISE EXCEPTION 'A moved allocation changes only through another move draft or a credit Adjustment'
                USING ERRCODE='P4904'; END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER payment_allocation_reversals_wrong_unit_move AFTER INSERT
            ON app.payment_allocation_reversals DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION app.validate_wrong_unit_move_reversal();

        -- Q-2026-10-05-18 and -19: a Credit released from a moved allocation is reversed back onto
        -- the Payment only when the Payment is a normal Customer Payment and the Credit is its
        -- payer's; a third-party Payment's value could otherwise reach another Customer.
        CREATE FUNCTION app.validate_moved_credit_reversal()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM app.invoice_credit_excess_releases release
                JOIN app.payment_allocations moved ON moved.id=release.reversed_payment_allocation_id
                JOIN app.customer_credits credit ON credit.id=release.customer_credit_id
                JOIN app.payments payment ON payment.id=moved.payment_id
                WHERE release.customer_credit_id=NEW.customer_credit_id
                  AND moved.between_invoice_basis='WRONG_UNIT_MOVE'
                  AND (credit.customer_id<>payment.payer_customer_id
                      OR payment.payment_scope_kind<>'NORMAL_CUSTOMER'))
            THEN RAISE EXCEPTION 'A Credit released from a moved Payment stays with its Customer; apply it to that Customer''s Invoices'
                USING ERRCODE='P4904'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER customer_credit_reversals_moved_payment BEFORE INSERT
            ON app.customer_credit_reversals FOR EACH ROW
            EXECUTE FUNCTION app.validate_moved_credit_reversal();

        -- Internal: the current move of one wrong Invoice allocation to the correct Invoice, or a
        -- refusal. Business-state refusals use 55000 (a conflict); a wrong request uses 22023.
        -- Timestamps render in UTC so that the stale check compares equal values in every session.
        CREATE FUNCTION app.payment_move_source(p_property uuid,p_allocation uuid,p_target_invoice uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_allocation app.payment_allocations%ROWTYPE; v_payment app.payments%ROWTYPE;
            v_source_invoice app.invoices%ROWTYPE; v_target app.invoices%ROWTYPE;
            v_source_unit uuid; v_target_unit uuid; v_reversed boolean; v_outstanding bigint;
            v_moved bigint; v_remaining bigint; v_amount bigint; v_count integer:=0;
            v_details jsonb:='[]'::jsonb; v_line record;
        BEGIN
            SELECT allocation.* INTO v_allocation FROM app.payment_allocations allocation
            JOIN app.payments payment ON payment.id=allocation.payment_id
            WHERE allocation.id=p_allocation AND payment.property_id=p_property;
            IF NOT FOUND THEN RAISE EXCEPTION 'Payment allocation was not found' USING ERRCODE='P0002'; END IF;
            SELECT * INTO v_target FROM app.invoices WHERE id=p_target_invoice;
            IF NOT FOUND OR app.invoice_property_id(v_target.id) IS DISTINCT FROM p_property
            THEN RAISE EXCEPTION 'Invoice was not found' USING ERRCODE='P0002'; END IF;
            -- BR-PAY-042 names Invoices: Late-payment Charge allocations do not move.
            IF v_allocation.target_kind<>'INVOICE' THEN
                RAISE EXCEPTION 'Only an Invoice allocation can move' USING ERRCODE='22023'; END IF;
            SELECT * INTO STRICT v_payment FROM app.payments WHERE id=v_allocation.payment_id;
            SELECT * INTO STRICT v_source_invoice FROM app.invoices WHERE id=v_allocation.invoice_id;
            SELECT unit_id INTO v_source_unit FROM app.leases WHERE id=v_source_invoice.lease_id;
            SELECT unit_id INTO v_target_unit FROM app.leases WHERE id=v_target.lease_id;
            IF v_source_unit IS NULL OR v_target_unit IS NULL OR v_source_unit=v_target_unit THEN
                RAISE EXCEPTION 'The correct Invoice must belong to a Lease of another Unit' USING ERRCODE='22023';
            END IF;
            IF v_payment.status<>'RECEIVED' THEN
                RAISE EXCEPTION 'The Payment is reversed' USING ERRCODE='55000'; END IF;
            -- A wrong allocation moves at most once; value a credit Adjustment released is moved
            -- through its replacement allocation.
            IF EXISTS (SELECT 1 FROM app.payment_moves WHERE source_allocation_id=p_allocation) THEN
                RAISE EXCEPTION 'This allocation was already moved' USING ERRCODE='55000'; END IF;
            IF EXISTS (SELECT 1 FROM app.invoice_credit_excess_releases
                WHERE reversed_payment_allocation_id=p_allocation)
            THEN RAISE EXCEPTION 'A credit Adjustment released this allocation' USING ERRCODE='55000'; END IF;
            v_reversed:=EXISTS (SELECT 1 FROM app.payment_allocation_reversals
                WHERE payment_allocation_id=p_allocation);
            -- Answer 4: Credit and Refunds are recorded per Payment, so any Credit not reversed or
            -- any Refund not fully returned blocks the move.
            IF app.payment_credit_value_at(v_payment.id,'infinity'::timestamptz)>0
                OR app.payment_refunded_value_at(v_payment.id,'infinity'::timestamptz)>0
            THEN RAISE EXCEPTION 'Reverse the Customer Credit or Refund from this Payment first'
                USING ERRCODE='55000'; END IF;
            IF v_target.status NOT IN ('UNPAID','PARTIALLY_PAID') THEN
                RAISE EXCEPTION 'The correct Invoice has nothing outstanding' USING ERRCODE='55000'; END IF;
            SELECT COALESCE(sum(app.invoice_line_outstanding(line.id)),0)::bigint INTO v_outstanding
            FROM app.invoice_lines line WHERE line.invoice_id=v_target.id;
            IF v_outstanding<=0 THEN
                RAISE EXCEPTION 'The correct Invoice has nothing outstanding' USING ERRCODE='55000'; END IF;
            -- The whole wrong allocation moves; if the correct Invoice owes less, the rest stays
            -- unallocated on the Payment (plan Q16).
            v_moved:=LEAST(v_allocation.amount_usd_cents,v_outstanding);
            -- Answer 5: an allocation already reversed by the one-call reversal moves only while the
            -- Payment still holds the value.
            IF v_reversed AND app.payment_available_value(v_payment.id)<v_moved THEN
                RAISE EXCEPTION 'The Payment no longer holds the value to move' USING ERRCODE='55000'; END IF;
            -- BR-PAY-036 order on the correct Invoice: Rent, then Service charges, then other lines.
            v_remaining:=v_moved;
            FOR v_line IN SELECT line.id,line.category,app.invoice_line_outstanding(line.id) AS outstanding
                FROM app.invoice_lines line WHERE line.invoice_id=v_target.id
                ORDER BY CASE line.category WHEN 'RENT' THEN 0 WHEN 'SERVICE_CHARGES' THEN 1 ELSE 2 END,
                    line.line_sequence,line.id
            LOOP
                EXIT WHEN v_remaining=0;
                CONTINUE WHEN v_line.outstanding<=0;
                v_count:=v_count+1;
                IF v_count>500 THEN
                    RAISE EXCEPTION 'The correct Invoice has too many lines for one move' USING ERRCODE='55000';
                END IF;
                v_amount:=LEAST(v_remaining,v_line.outstanding);
                v_details:=v_details||jsonb_build_array(jsonb_build_object(
                    'invoice_line_id',v_line.id,'category',v_line.category,'amount_usd_cents',v_amount,
                    'attribution_basis',CASE v_line.category WHEN 'RENT' THEN 'RENT_FIRST_PROPOSAL'
                        WHEN 'SERVICE_CHARGES' THEN 'SERVICE_PROPOSAL' ELSE 'OTHER_CONFIRMED' END));
                v_remaining:=v_remaining-v_amount;
            END LOOP;
            RETURN jsonb_build_object('payment_id',v_payment.id,'payer_customer_id',v_payment.payer_customer_id,
                'source_invoice_id',v_source_invoice.id,'source_customer_id',v_source_invoice.customer_id,
                'source_unit_id',v_source_unit,'source_amount_usd_cents',v_allocation.amount_usd_cents,
                'source_reversed',v_reversed,'target_customer_id',v_target.customer_id,
                'target_unit_id',v_target_unit,'moved_usd_cents',v_moved,'details',v_details,
                'target_version',v_target.version,'target_updated_at',v_target.updated_at,
                'target_latest_at',app.allocation_target_latest_at('INVOICE',v_target.id));
        END $$;

        -- Staff record the move as a draft (payments.allocations.reverse); it has no financial
        -- effect until a financial.approve holder confirms.
        CREATE FUNCTION app.record_payment_move_draft(p_property uuid,p_actor uuid,p_draft uuid,
            p_allocation uuid,p_target_invoice uuid,p_reason text,p_source_acknowledgement text,
            p_target_acknowledgement text,p_authorization text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_input jsonb; v_payload jsonb; v_source jsonb; v_existing app.financial_drafts%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property,p_actor);
            PERFORM app.assert_active_financial_actor(p_actor,p_property);
            IF p_authorization IS DISTINCT FROM 'payments.allocations.reverse'
            THEN RAISE EXCEPTION 'Payment move draft authorization is invalid' USING ERRCODE='42501'; END IF;
            IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_allocation IS NULL
                OR p_target_invoice IS NULL
                OR app.lease_notice_text_valid(p_reason,1000) IS NOT TRUE
                OR app.lease_notice_text_valid(p_source_acknowledgement,2000) IS NOT TRUE
                OR app.lease_notice_text_valid(p_target_acknowledgement,2000) IS NOT TRUE
            THEN RAISE EXCEPTION 'Payment move draft input is invalid' USING ERRCODE='22023'; END IF;
            v_input:=jsonb_build_object('variant','WRONG_UNIT_MOVE','source_allocation_id',p_allocation,
                'target_invoice_id',p_target_invoice,'source_acknowledgement',p_source_acknowledgement,
                'target_acknowledgement',p_target_acknowledgement);
            -- An exact repeat replays before any current-state check.
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
            SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
            IF FOUND THEN
                IF v_existing.property_id=p_property AND v_existing.kind='PAYMENT_MOVE'
                    AND v_existing.prepared_by=p_actor AND v_existing.reason=p_reason
                    AND (v_existing.payload-'source')=v_input
                THEN RETURN app.financial_draft_json(v_existing); END IF;
                RAISE EXCEPTION 'Payment move draft identity was reused' USING ERRCODE='P5205';
            END IF;
            -- The Property is checked before the lock; drafts of one allocation are then
            -- serialized, so only one may wait.
            v_source:=app.payment_move_source(p_property,p_allocation,p_target_invoice);
            PERFORM pg_advisory_xact_lock(hashtextextended('payment-move:' || p_allocation::text,0));
            v_source:=app.payment_move_source(p_property,p_allocation,p_target_invoice);
            IF EXISTS (SELECT 1 FROM app.financial_drafts draft
                WHERE draft.property_id=p_property AND draft.kind='PAYMENT_MOVE'
                  AND draft.payload->>'source_allocation_id'=p_allocation::text
                  AND NOT EXISTS (SELECT 1 FROM app.financial_draft_decisions decision
                      WHERE decision.draft_id=draft.id))
            THEN RAISE EXCEPTION 'A move draft for this allocation is already waiting' USING ERRCODE='55000'; END IF;
            v_payload:=v_input || jsonb_build_object('source',v_source);
            IF octet_length(v_payload::text)>16000 THEN
                RAISE EXCEPTION 'The move draft exceeds the stored draft size of 16000 bytes (acknowledgements and the line split of the correct Invoice)'
                    USING ERRCODE='22023'; END IF;
            RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'PAYMENT_MOVE',
                'payments.allocations.reverse',v_payload,
                'payment-move:' || encode(sha256(convert_to(v_source::text,'UTF8')),'hex'),p_reason);
        END $$;

        -- A financial.approve holder confirms: the wrong allocation is reversed (unless already
        -- reversed) and the same Payment is allocated to the correct Invoice, in one transaction.
        CREATE FUNCTION app.confirm_payment_move_draft(p_property uuid,p_actor uuid,p_draft uuid,
            p_authorization text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE; v_source jsonb; v_invoice app.invoices%ROWTYPE;
            v_payment uuid; v_source_allocation uuid; v_source_invoice uuid; v_target_invoice uuid;
            v_reversal uuid; v_allocation uuid:=gen_random_uuid(); v_move uuid:=gen_random_uuid();
            v_by_move boolean; v_at timestamptz; v_detail jsonb; v_sequence integer:=0; v_result jsonb;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property,p_actor);
            PERFORM app.assert_active_financial_actor(p_actor,p_property);
            IF p_authorization IS DISTINCT FROM 'financial.approve' THEN
                RAISE EXCEPTION 'Only financial.approve may confirm a Payment move draft' USING ERRCODE='42501'; END IF;
            IF p_draft IS NULL THEN
                RAISE EXCEPTION 'Payment move confirmation is invalid' USING ERRCODE='22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
            SELECT draft.* INTO v_draft FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
            WHERE draft.id=p_draft AND draft.property_id=p_property AND draft.kind='PAYMENT_MOVE'
              AND decision.decision='CONFIRMED' AND decision.decided_by=p_actor;
            IF FOUND THEN
                -- An exact replay returns the stored result of the first confirmation.
                RETURN jsonb_build_object('draft',app.financial_draft_json(v_draft),'move',
                    (SELECT decision.result FROM app.financial_draft_decisions decision
                     WHERE decision.draft_id=p_draft));
            END IF;
            v_draft:=app.lock_pending_financial_draft(p_property,p_draft);
            IF v_draft.kind<>'PAYMENT_MOVE' OR v_draft.prepare_capability<>'payments.allocations.reverse'
                OR v_draft.payload->>'variant' IS DISTINCT FROM 'WRONG_UNIT_MOVE'
            THEN RAISE EXCEPTION 'Financial draft was not found' USING ERRCODE='P0002'; END IF;
            v_source_allocation:=(v_draft.payload->>'source_allocation_id')::uuid;
            v_target_invoice:=(v_draft.payload->>'target_invoice_id')::uuid;
            v_payment:=(v_draft.payload->'source'->>'payment_id')::uuid;
            v_source_invoice:=(v_draft.payload->'source'->>'source_invoice_id')::uuid;
            PERFORM pg_advisory_xact_lock(hashtextextended('payment-move:' || v_source_allocation::text,0));
            -- The allocation commands' lock order: Payment state, Payment row, then Invoices.
            PERFORM app.serialize_payment_state(v_payment);
            PERFORM 1 FROM app.payments WHERE id=v_payment FOR UPDATE;
            PERFORM 1 FROM app.invoices WHERE id IN (v_source_invoice,v_target_invoice) ORDER BY id FOR UPDATE;
            PERFORM 1 FROM app.invoice_lines WHERE invoice_id=v_target_invoice ORDER BY id FOR UPDATE;
            v_source:=app.payment_move_source(p_property,v_source_allocation,v_target_invoice);
            -- A draft is stale when anything it relied on changed; it stays pending.
            IF v_source IS DISTINCT FROM v_draft.payload->'source' THEN
                RAISE EXCEPTION 'Payment move draft is stale' USING ERRCODE='55000'; END IF;
            SET CONSTRAINTS ALL DEFERRED;
            -- One instant for the reversal and the new allocation, strictly later than every
            -- financial event of both Invoices, so the Payment is never over-used in between.
            v_at:=GREATEST(app.credit_excess_instant(v_source_invoice,NULL),
                app.credit_excess_instant(v_target_invoice,NULL));
            v_by_move:=NOT (v_source->>'source_reversed')::boolean;
            IF v_by_move THEN
                v_reversal:=gen_random_uuid();
                INSERT INTO app.payment_allocation_reversals(id,payment_allocation_id,reason,occurred_at,
                    actor_id,authorization_reference)
                VALUES(v_reversal,v_source_allocation,v_draft.reason,v_at,p_actor,
                    'payments.allocations.reverse');
            ELSE
                SELECT id INTO STRICT v_reversal FROM app.payment_allocation_reversals
                WHERE payment_allocation_id=v_source_allocation;
            END IF;
            SELECT * INTO STRICT v_invoice FROM app.invoices WHERE id=v_target_invoice;
            INSERT INTO app.payment_allocations(id,payment_id,target_customer_id,proposal_batch_id,
                between_invoice_sequence,target_kind,invoice_id,late_payment_charge_id,amount_usd_cents,
                between_invoice_basis,within_invoice_basis,customer_designation_reference,
                selected_invoice_due_date,selected_invoice_issued_at,selected_invoice_number_snapshot,
                proposal_generated_at,proposal_trace,posted_at,posted_by,authorization_reference)
            VALUES(v_allocation,v_payment,v_invoice.customer_id,gen_random_uuid(),1,'INVOICE',
                v_target_invoice,NULL,(v_source->>'moved_usd_cents')::bigint,'WRONG_UNIT_MOVE',
                'RENT_THEN_RECURRING_SERVICES_PROPOSAL',NULL,v_invoice.due_date,v_invoice.issued_at,
                v_invoice.invoice_number,v_at,jsonb_build_object('variant','WRONG_UNIT_MOVE',
                    'payment_move_draft_id',p_draft,'source_allocation_id',v_source_allocation,
                    'source_reversal_id',v_reversal),v_at,p_actor,'payments.allocate');
            FOR v_detail IN SELECT value FROM jsonb_array_elements(v_source->'details') LOOP
                v_sequence:=v_sequence+1;
                INSERT INTO app.payment_allocation_details(id,payment_allocation_id,invoice_line_id,
                    obligation_kind,invoice_line_category_snapshot,proposed_amount_usd_cents,
                    posted_amount_usd_cents,attribution_basis,detail_sequence,calculation_trace)
                VALUES(gen_random_uuid(),v_allocation,(v_detail->>'invoice_line_id')::uuid,'INVOICE_LINE',
                    v_detail->>'category',(v_detail->>'amount_usd_cents')::bigint,
                    (v_detail->>'amount_usd_cents')::bigint,v_detail->>'attribution_basis',
                    v_sequence::smallint,jsonb_build_object('payment_move_draft_id',p_draft,
                        'confirmed_detail',v_detail));
            END LOOP;
            -- Advance the correct Invoice's version even when its status stays the same, as every
            -- other allocation writer does, so a command prepared before the move is stale.
            PERFORM app.refresh_allocated_invoice(v_target_invoice,p_actor,true);
            INSERT INTO app.payment_moves(id,draft_id,property_id,payment_id,source_allocation_id,
                source_reversal_id,source_reversed_by_move,target_allocation_id,source_invoice_id,
                target_invoice_id,moved_usd_cents,source_acknowledgement,target_acknowledgement,
                confirmed_at,confirmed_by)
            VALUES(v_move,p_draft,p_property,v_payment,v_source_allocation,v_reversal,v_by_move,
                v_allocation,v_source_invoice,v_target_invoice,(v_source->>'moved_usd_cents')::bigint,
                v_draft.payload->>'source_acknowledgement',v_draft.payload->>'target_acknowledgement',
                clock_timestamp(),p_actor);
            v_result:=jsonb_build_object('payment_move_id',v_move,'payment_id',v_payment,
                'source_allocation_id',v_source_allocation,'source_reversal_id',v_reversal,
                'source_reversed_by_move',v_by_move,'target_allocation_id',v_allocation,
                'source_invoice_id',v_source_invoice,'target_invoice_id',v_target_invoice,
                'moved_usd_cents',(v_source->>'moved_usd_cents')::bigint,
                'payment_available_usd_cents',app.payment_available_value(v_payment));
            PERFORM app.confirm_financial_draft_record(p_property,p_actor,p_draft,'PAYMENT_MOVE',
                v_result,'financial.approve');
            -- One audit event for the whole move; its correlation id is the draft id.
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,resulting_state,correlation_id,source,outcome,
                customer_id,lease_id)
            VALUES(gen_random_uuid(),v_at,(v_at AT TIME ZONE 'Asia/Phnom_Penh')::date,p_actor,
                'payment_move.confirmed','payment_move',v_move,v_draft.reason,'financial.approve',p_property,
                v_result||jsonb_build_object('prepared_by_actor_id',v_draft.prepared_by,
                    'source_customer_id',v_source->>'source_customer_id',
                    'target_customer_id',v_source->>'target_customer_id'),
                p_draft,'API','SUCCESS',v_invoice.customer_id,v_invoice.lease_id);
            SET CONSTRAINTS ALL IMMEDIATE;
            RETURN jsonb_build_object('draft',app.financial_draft_json(v_draft),'move',v_result);
        END $$;
    """)
    op.execute(
        "REVOKE ALL ON TABLE app.payment_moves FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for function in (SOURCE, RECORD_DRAFT, CONFIRM_DRAFT, *GUARDS):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD_DRAFT}, {CONFIRM_DRAFT} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Payment move draft migration is forward-only")
