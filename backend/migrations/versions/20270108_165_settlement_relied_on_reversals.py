# ruff: noqa: E501
"""Refusals after closure of what a closed Final Settlement relied on (V1-056 sub-slice 10h-1).

BR-SETTLE-012, BR-SETTLE-013, BR-SETTLE-016, BR-PAY-042, BR-AUTH-010; DB-SETTLE-005, DB-PAY-008;
owner answers 3 and 4 to Q-2026-10-06-36, answer 5 to Q-2026-10-06-37, the answer to
Q-2026-10-07-39, the owner note of 2026-10-16 on the 10f-2 report and owner answer (a) to
Q-2026-10-17-120 point 2: once a Final Settlement is closed, an allocation or Credit application it
relied on changes only through a post-settlement correction of that Settlement.

- What a closed Settlement relied on (the definition of sub-slice 10e-1a): an allocation or Credit
  application on an obligation of its Lease (an Invoice of the Lease, or a Late-payment Charge whose
  source Invoice is of the Lease) made at or before the closure, a Final Settlement Credit
  application, and a record linked to a correction of that Settlement. The re-posted rest of a
  closure-era record is made before the closure or written by a correction and linked, so it is
  covered (Q-2026-10-07-39). New internal app.closed_settlements_relying_on_allocation and
  app.closed_settlements_relying_on_credit_application (no grant) return those Settlements.
- New BEFORE INSERT triggers a0_payment_allocation_reversals_relied_on and
  a1_customer_credit_application_reversals_relied_on refuse (P5S01, the 8e-1 text) a reversal of
  such a record unless, for every Settlement that relied on it, a correction of that Settlement
  confirmed in this transaction links the reversal (app.settlement_correction_linked). Every
  correction writer links before it writes. They first take the insert check's own locks in its
  order, so a Final Settlement started or closed during a lock wait is read after it, then the
  Settlement row of the target's Lease FOR SHARE (the 8e-1 order), so a running Final Settlement
  confirm is waited for and its closure is then read; a record with no Settlement on its Lease and
  no correction link takes no Settlement lock. So the one-call allocation and Credit application
  reversals of such a record are refused, an ordinary credit Adjustment or another Lease's REFUND
  correction cannot release an allocation a PAYMENT_MOVE correction wrote on that Lease, the
  put-back of an ADJUSTMENT_REVERSAL correction cannot be undone by the one-call reversal, and a
  record two closed Settlements relied on stays refused (Q-2026-10-17-120 point 1). Records made
  after the closure and not linked stay reversible. The Credit trigger is named to run after the
  8e-2 and 10c-1b refusals, so their texts stay first for their records.
- app.payment_move_source (the slice 7 move source; whole-body replacement, same signature,
  settings and privileges) refuses (55000) an allocation a closed Settlement relied on before it
  calls app.wrong_unit_move_source, so the slice 7 recorder and confirm refuse it; such an
  allocation moves through the PAYMENT_MOVE correction (sub-slice 10g), whose source is not
  changed. An allocation reversed at or before a Settlement's closure is not one that Settlement
  relied on, so it keeps the slice 7 rules.

Additive or relaxing in form: two new internal functions, two new trigger functions and two
triggers (fail-closed refusals the owner approved), and one whole-body replacement. No table,
column, constraint or grant change beyond the new functions' revokes.
"""

from alembic import op

revision = "20270108_165"
down_revision = "20270107_164"
branch_labels = None
depends_on = None

INTERNAL = (
    "app.closed_settlements_relying_on_allocation(uuid)",
    "app.closed_settlements_relying_on_credit_application(uuid)",
    "app.refuse_relied_on_allocation_reversal()",
    "app.refuse_relied_on_credit_application_reversal()",
)

SQL = r"""
    -- Sub-slice 10h-1: the closed Final Settlements that relied on an allocation (the definition
    -- of sub-slice 10e-1a, owner answer 5 to Q-2026-10-06-37): made at or before the closure on an
    -- obligation of the Settlement's Lease, or linked to a correction of the Settlement.
    CREATE FUNCTION app.closed_settlements_relying_on_allocation(p_allocation uuid)
    RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT settlement.id FROM app.payment_allocations allocation
        LEFT JOIN app.late_payment_charges charge ON charge.id=allocation.late_payment_charge_id
        JOIN app.invoices invoice ON invoice.id=COALESCE(allocation.invoice_id,charge.source_invoice_id)
        JOIN app.final_settlements settlement
            ON settlement.lease_id=invoice.lease_id AND settlement.closed_at IS NOT NULL
        WHERE allocation.id=p_allocation AND allocation.posted_at<=settlement.closed_at
        UNION
        SELECT correction.final_settlement_id FROM app.settlement_correction_effects effect
        JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
        WHERE effect.payment_allocation_id=p_allocation
    $$;

    -- The same for a Credit application; a Final Settlement Credit application is relied on by
    -- its own Settlement.
    CREATE FUNCTION app.closed_settlements_relying_on_credit_application(p_application uuid)
    RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT application.final_settlement_id FROM app.customer_credit_applications application
        WHERE application.id=p_application AND application.final_settlement_id IS NOT NULL
        UNION
        SELECT settlement.id FROM app.customer_credit_applications application
        LEFT JOIN app.late_payment_charges charge ON charge.id=application.late_payment_charge_id
        JOIN app.invoices invoice ON invoice.id=COALESCE(application.invoice_id,charge.source_invoice_id)
        JOIN app.final_settlements settlement
            ON settlement.lease_id=invoice.lease_id AND settlement.closed_at IS NOT NULL
        WHERE application.id=p_application AND application.occurred_at<=settlement.closed_at
        UNION
        SELECT correction.final_settlement_id FROM app.settlement_correction_effects effect
        JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
        WHERE effect.customer_credit_application_id=p_application
    $$;

    -- Owner answers 3 and 4 to Q-2026-10-06-36 and point 2 of Q-2026-10-17-120: an allocation a
    -- closed Final Settlement relied on is reversed only through a correction of that Settlement
    -- confirmed in this transaction, for every writer.
    CREATE FUNCTION app.refuse_relied_on_allocation_reversal()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_allocation app.payment_allocations%ROWTYPE; v_lease uuid; v_settlement uuid;
    BEGIN
        SELECT * INTO v_allocation FROM app.payment_allocations WHERE id=NEW.payment_allocation_id;
        -- An unknown allocation is refused by the insert check.
        IF NOT FOUND THEN RETURN NEW; END IF;
        SELECT invoice.lease_id INTO v_lease FROM app.invoices invoice
        WHERE invoice.id=COALESCE(v_allocation.invoice_id,(SELECT charge.source_invoice_id
            FROM app.late_payment_charges charge WHERE charge.id=v_allocation.late_payment_charge_id));
        -- The insert check's locks in its order first, so a Final Settlement started or closed
        -- during a lock wait is read after it (review round 1, security note 1).
        PERFORM app.serialize_payment_state(v_allocation.payment_id);
        PERFORM 1 FROM app.payments WHERE id=v_allocation.payment_id FOR UPDATE;
        PERFORM app.lock_payment_allocation_target(v_allocation.target_kind,
            COALESCE(v_allocation.invoice_id,v_allocation.late_payment_charge_id));
        -- No Final Settlement on the target's Lease and no correction link: no change.
        IF NOT EXISTS(SELECT 1 FROM app.final_settlements settlement WHERE settlement.lease_id=v_lease)
            AND NOT EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                WHERE effect.payment_allocation_id=v_allocation.id)
        THEN RETURN NEW; END IF;
        -- Then the Settlement row (the 8e-1 order): a running Final Settlement confirm is waited
        -- for and its closure is then read.
        PERFORM 1 FROM app.final_settlements settlement WHERE settlement.lease_id=v_lease FOR SHARE;
        -- An allocation reversed before the closure is not reversed again either way; for it this
        -- refusal comes before the duplicate refusal (review round 2, independent note 2).
        FOR v_settlement IN SELECT relied.settlement_id
            FROM app.closed_settlements_relying_on_allocation(v_allocation.id) relied(settlement_id)
        LOOP
            IF app.settlement_correction_linked(v_settlement,'payment_allocation_reversals',NEW.id)
                IS NOT TRUE
            THEN RAISE EXCEPTION 'A closed Final Settlement changes only through a post-settlement correction'
                USING ERRCODE='P5S01'; END IF;
        END LOOP;
        RETURN NEW;
    END $$;

    -- The same for a Credit application (it also closes the post-closure put-back gap of the
    -- owner note of 2026-10-16: an ADJUSTMENT_REVERSAL correction's put-back is linked to it).
    CREATE FUNCTION app.refuse_relied_on_credit_application_reversal()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_application app.customer_credit_applications%ROWTYPE;
        v_credit app.customer_credits%ROWTYPE; v_lease uuid; v_settlement uuid;
    BEGIN
        SELECT * INTO v_application FROM app.customer_credit_applications
        WHERE id=NEW.credit_application_id;
        -- An unknown application is refused by the insert check.
        IF NOT FOUND THEN RETURN NEW; END IF;
        SELECT * INTO STRICT v_credit FROM app.customer_credits WHERE id=v_application.customer_credit_id;
        SELECT invoice.lease_id INTO v_lease FROM app.invoices invoice
        WHERE invoice.id=COALESCE(v_application.invoice_id,(SELECT charge.source_invoice_id
            FROM app.late_payment_charges charge WHERE charge.id=v_application.late_payment_charge_id));
        -- The insert check's locks in its order first (review round 1, security note 1).
        PERFORM app.serialize_payment_state(v_credit.source_payment_id);
        PERFORM 1 FROM app.payments WHERE id=v_credit.source_payment_id FOR UPDATE;
        PERFORM 1 FROM app.customer_credits WHERE id=v_credit.id FOR UPDATE;
        PERFORM app.lock_payment_allocation_target(v_application.target_kind,
            COALESCE(v_application.invoice_id,v_application.late_payment_charge_id));
        -- No Final Settlement on the target's Lease or the row, and no correction link: no change.
        IF v_application.final_settlement_id IS NULL
            AND NOT EXISTS(SELECT 1 FROM app.final_settlements settlement WHERE settlement.lease_id=v_lease)
            AND NOT EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                WHERE effect.customer_credit_application_id=v_application.id)
        THEN RETURN NEW; END IF;
        -- Then the Settlement row (the 8e-1 order).
        PERFORM 1 FROM app.final_settlements settlement WHERE settlement.lease_id=v_lease FOR SHARE;
        FOR v_settlement IN SELECT relied.settlement_id
            FROM app.closed_settlements_relying_on_credit_application(v_application.id) relied(settlement_id)
        LOOP
            IF app.settlement_correction_linked(v_settlement,'customer_credit_application_reversals',NEW.id)
                IS NOT TRUE
            THEN RAISE EXCEPTION 'A closed Final Settlement changes only through a post-settlement correction'
                USING ERRCODE='P5S01'; END IF;
        END LOOP;
        RETURN NEW;
    END $$;

    CREATE TRIGGER a0_payment_allocation_reversals_relied_on
        BEFORE INSERT ON app.payment_allocation_reversals
        FOR EACH ROW EXECUTE FUNCTION app.refuse_relied_on_allocation_reversal();
    -- After the a0_ refusals of 8e-2 and 10c-1b, so their texts stay first for their records.
    CREATE TRIGGER a1_customer_credit_application_reversals_relied_on
        BEFORE INSERT ON app.customer_credit_application_reversals
        FOR EACH ROW EXECUTE FUNCTION app.refuse_relied_on_credit_application_reversal();

    -- Sub-slice 10h-1 (owner answers 3 and 4 to Q-2026-10-06-36 and point 2 of
    -- Q-2026-10-17-120): an allocation a closed Final Settlement relied on moves only through a
    -- PAYMENT_MOVE correction of that Settlement; the slice 7 move draft keeps the blanket Credit
    -- and Refund refusal (sub-slice 10g-2), and the one body is app.wrong_unit_move_source.
    CREATE OR REPLACE FUNCTION app.payment_move_source(p_property uuid,p_allocation uuid,p_target_invoice uuid)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
    BEGIN
        -- An allocation of another Property gets the slice 7 not-found refusal from the body. A
        -- Settlement did not rely on an allocation reversed at or before its closure, so such an
        -- allocation keeps the slice 7 rules (review round 1, independent S1).
        IF EXISTS(SELECT 1 FROM app.payment_allocations allocation
                JOIN app.payments payment ON payment.id=allocation.payment_id
                WHERE allocation.id=p_allocation AND payment.property_id=p_property)
            AND EXISTS(SELECT 1
                FROM app.closed_settlements_relying_on_allocation(p_allocation) relied(settlement_id)
                JOIN app.final_settlements settlement ON settlement.id=relied.settlement_id
                WHERE NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                    WHERE reversal.payment_allocation_id=p_allocation
                      AND reversal.occurred_at<=settlement.closed_at))
        THEN RAISE EXCEPTION 'A closed Final Settlement relied on this allocation; move it through a correction of that Final Settlement'
            USING ERRCODE='55000'; END IF;
        RETURN app.wrong_unit_move_source(p_property,p_allocation,p_target_invoice,false);
    END $$;
"""


def upgrade() -> None:
    # CREATE OR REPLACE keeps the slice 7 source's identity, owner and privileges.
    op.execute(SQL)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Settlement relied-on reversal migration is forward-only")
