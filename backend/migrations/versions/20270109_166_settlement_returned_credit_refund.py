# ruff: noqa: E501
"""The ordinary Credit Refund draft and money a correction brought back (V1-056 sub-slice 10h-1b).

BR-SETTLE-013, BR-SETTLE-004, BR-CREDIT-011, BR-CREDIT-014, BR-REFUND-002, BR-AUTH-010, DL-032;
DB-SETTLE-005; owner answer (b) to Q-2026-10-19-141: money that a post-settlement correction brought
back into a Customer Credit (a returned Refund's VALUE_CORRECTION linked to a correction) leaves
only through a correction of that Final Settlement, so the Customer's open debt on the Lease is paid
first (a HELD_VALUE_REFUND correction naming the return). The ordinary Credit Refund draft (slice
3a-1, variant USD with a CREDIT source; sub-slice 8f, variant CREDIT_CUSTOMER) is refused for that
money; money the Credit holds for other reasons stays refundable through it.

- New internal app.credit_settlement_returned_value_by_settlement and
  app.credit_settlement_returned_value_left (no grant): what every return into the Credit has left
  by the returned-value count (app.settlement_returned_value_left, sub-slices 10e-3d to 10e-3d-2d),
  for each Final Settlement whose corrections returned money into it, and its sum; 0 when none did.
- New internal app.refuse_credit_refund_of_returned_value (no grant): P5S01 when that left value is
  above 0 and the Refund amount is more than the Credit's available value less that left value.
- app.record_refund_draft (the twelve-argument overload) and app.record_credit_customer_refund_draft
  call it for a Credit source after their current-state checks (an exact repeat still replays
  first); app.confirm_refund_draft first takes the Credit Refund locks (the Payment state guard, the
  Payment, then the Credit, the order the writers take next) and then calls it, so the draft stays
  pending. One exact-text replacement each, checked to match once; signatures, settings and
  privileges are kept.
- Owner answer (a) to Q-2026-10-19-144: a new BEFORE INSERT trigger on
  app.customer_credit_reversals (internal app.refuse_returned_credit_reversal, no grant) takes the
  Credit Refund locks first and refuses (P5S01) a Credit reversal while those returns have money
  left, unless a correction of each such Settlement confirmed in this transaction links it. So the
  one-call Credit reversal cannot move that money back to its Payment, from which a Payment Refund
  or a new Credit would pay it out without the Settlement; the RETURNED_PAYMENT correction links
  first and still reverses the Credit.

Fail-closed refusals the owner approved: four new internal functions, one new trigger and three
exact-text replacements. No table, column, constraint or grant change. Not changed: the Payment
and Pet Deposit Refund drafts, Credit applications outside a correction, every correction writer
and the owner-only one-call writer app.create_usd_refund.
"""

from alembic import op
from sqlalchemy import text

revision = "20270109_166"
down_revision = "20270108_165"
branch_labels = None
depends_on = None

INTERNAL = (
    "app.credit_settlement_returned_value_by_settlement(uuid)",
    "app.credit_settlement_returned_value_left(uuid)",
    "app.refuse_credit_refund_of_returned_value(uuid,bigint)",
    "app.refuse_returned_credit_reversal()",
)
RECORD = "app.record_refund_draft(uuid,uuid,uuid,text,text,uuid,uuid,bigint,text,uuid,text,text)"
RECORD_CREDIT_CUSTOMER = (
    "app.record_credit_customer_refund_draft(uuid,uuid,uuid,uuid,bigint,text,uuid,text,text)"
)
CONFIRM = "app.confirm_refund_draft(uuid,uuid,uuid,text)"

INTERNAL_SQL = """
    CREATE FUNCTION app.credit_settlement_returned_value_by_settlement(p_credit uuid)
    RETURNS TABLE(final_settlement_id uuid,left_usd_cents bigint)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        -- Sub-slice 10h-1b (owner answer (b) to Q-2026-10-19-141): for each Final Settlement
        -- whose corrections returned money into the Credit (the walk's own entry rule: a linked
        -- VALUE_CORRECTION of a Refund from the Credit), what those returns have left by the
        -- returned-value count. A Settlement's walk also lists the entries of another
        -- Settlement's corrections that used the Credit (sub-slice 10e-3d-2d-1), so each
        -- Settlement counts only its own corrections' entries (review round 1, independent S1).
        SELECT settlement.final_settlement_id,
            COALESCE(sum(GREATEST(counted.left_usd_cents,0)),0)::bigint
        FROM (
            SELECT DISTINCT correction.final_settlement_id
            FROM app.settlement_correction_effects effect
            JOIN app.settlement_corrections correction
                ON correction.id=effect.settlement_correction_id
            JOIN app.refund_corrections returned ON returned.id=effect.refund_correction_id
            JOIN app.refunds origin ON origin.id=returned.refund_id
            WHERE returned.correction_kind='VALUE_CORRECTION'
              AND origin.source_customer_credit_id=p_credit
        ) settlement
        CROSS JOIN LATERAL app.settlement_returned_value_left(settlement.final_settlement_id,
            'CREDIT',p_credit,NULL) counted
        JOIN app.settlement_corrections entry
            ON entry.id=counted.settlement_correction_id
           AND entry.final_settlement_id=settlement.final_settlement_id
        GROUP BY settlement.final_settlement_id
    $$;

    -- What every post-settlement return into the Credit has left, summed over those Final
    -- Settlements; 0 when none returned money into it.
    CREATE FUNCTION app.credit_settlement_returned_value_left(p_credit uuid)
    RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE(sum(returned.left_usd_cents),0)::bigint
        FROM app.credit_settlement_returned_value_by_settlement(p_credit) returned
    $$;

    CREATE FUNCTION app.refuse_credit_refund_of_returned_value(p_credit uuid,p_amount bigint)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_left bigint;
    BEGIN
        -- Sub-slice 10h-1b (owner answer (b) to Q-2026-10-19-141): money a post-settlement
        -- correction brought back into the Credit leaves only through a correction of that Final
        -- Settlement (a HELD_VALUE_REFUND naming the return pays the Customer's open debt on the
        -- Lease first, DL-032); the Credit's other money stays refundable. A left value above
        -- what the Credit holds (ordinary Credit applications are not counted) refuses every
        -- ordinary Refund of it.
        v_left:=app.credit_settlement_returned_value_left(p_credit);
        IF v_left>0 AND p_amount>app.credit_available_value(p_credit)-v_left THEN
            RAISE EXCEPTION 'The Credit holds money a post-settlement correction brought back; refund that money through a held-value correction of that Final Settlement'
                USING ERRCODE='P5S01';
        END IF;
    END $$;

    -- Owner answer (a) to Q-2026-10-19-144: the one-call Credit reversal would move money a
    -- post-settlement correction brought back into the Credit to its Payment, from which a
    -- Payment Refund or a new Credit pays it out without the Settlement; so a Credit reversal is
    -- written while those returns have money left only when a correction of each such Settlement,
    -- confirmed in this transaction, links it (the RETURNED_PAYMENT correction links first).
    CREATE FUNCTION app.refuse_returned_credit_reversal()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_credit app.customer_credits%ROWTYPE; v_settlement uuid;
    BEGIN
        SELECT * INTO v_credit FROM app.customer_credits WHERE id=NEW.customer_credit_id;
        -- An unknown Credit is refused by the insert check.
        IF NOT FOUND THEN RETURN NEW; END IF;
        -- The insert check's locks in its order first (the Payment state guard, the Payment, then
        -- the Credit), so a return a correction committed during the wait is read after it.
        PERFORM app.lock_refund_payment_source(NULL,v_credit.id);
        FOR v_settlement IN SELECT returned.final_settlement_id
            FROM app.credit_settlement_returned_value_by_settlement(v_credit.id) returned
            WHERE returned.left_usd_cents>0
        LOOP
            IF app.settlement_correction_linked(v_settlement,'customer_credit_reversals',NEW.id)
                IS NOT TRUE
            THEN RAISE EXCEPTION 'A closed Final Settlement changes only through a post-settlement correction'
                USING ERRCODE='P5S01'; END IF;
        END LOOP;
        RETURN NEW;
    END $$;

    -- After the slice 7 and 8g refusals (their texts stay first for their Credits), before the
    -- insert check.
    CREATE TRIGGER customer_credit_reversals_returned_value
        BEFORE INSERT ON app.customer_credit_reversals
        FOR EACH ROW EXECUTE FUNCTION app.refuse_returned_credit_reversal();
"""

RECORD_REPLACEMENTS = (
    (
        "            IF p_variant = 'USD' THEN\n"
        "                PERFORM app.require_usd_refund_source(p_property_id, p_source_kind, p_source_id);\n"
        "            ELSIF ",
        "            IF p_variant = 'USD' THEN\n"
        "                PERFORM app.require_usd_refund_source(p_property_id, p_source_kind, p_source_id);\n"
        "                -- Sub-slice 10h-1b (owner answer (b) to Q-2026-10-19-141): money a\n"
        "                -- post-settlement correction brought back leaves only through a correction.\n"
        "                IF p_source_kind = 'CREDIT' THEN\n"
        "                    PERFORM app.refuse_credit_refund_of_returned_value(p_source_id, p_amount);\n"
        "                END IF;\n"
        "            ELSIF ",
    ),
)

RECORD_CREDIT_CUSTOMER_REPLACEMENTS = (
    (
        "            RETURN app.insert_financial_draft(\n",
        "            -- Sub-slice 10h-1b (owner answer (b) to Q-2026-10-19-141): money a post-settlement\n"
        "            -- correction brought back leaves only through a correction.\n"
        "            PERFORM app.refuse_credit_refund_of_returned_value(p_credit_id, p_amount);\n"
        "            RETURN app.insert_financial_draft(\n",
    ),
)

CONFIRM_REPLACEMENTS = (
    (
        "            IF v_draft.payload->>'variant' = 'CREDIT_CUSTOMER' THEN\n"
        "                -- BR-CREDIT-014 (V1-056 sub-slice 8f)",
        "            -- Sub-slice 10h-1b (owner answer (b) to Q-2026-10-19-141): a Credit Refund takes the\n"
        "            -- Credit Refund locks first (the Payment state guard, the Payment, then the Credit,\n"
        "            -- the order its writer takes next), so a return a correction committed is read; money\n"
        "            -- a post-settlement correction brought back leaves only through a correction, and\n"
        "            -- the draft stays pending.\n"
        "            IF v_draft.payload->>'source_kind' = 'CREDIT' THEN\n"
        "                PERFORM app.lock_refund_payment_source(\n"
        "                    NULL, (v_draft.payload->>'source_id')::uuid\n"
        "                );\n"
        "                PERFORM app.refuse_credit_refund_of_returned_value(\n"
        "                    (v_draft.payload->>'source_id')::uuid,\n"
        "                    (v_draft.payload->>'amount_usd_cents')::bigint\n"
        "                );\n"
        "            END IF;\n"
        "            IF v_draft.payload->>'variant' = 'CREDIT_CUSTOMER' THEN\n"
        "                -- BR-CREDIT-014 (V1-056 sub-slice 8f)",
    ),
)


def _definition(signature: str) -> str:
    return str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _replaced(signature: str, replacements: tuple[tuple[str, str], ...]) -> str:
    definition = _definition(signature)
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Settlement returned Credit Refund contract changed: {signature}")
        definition = definition.replace(before, after)
    return definition


def upgrade() -> None:
    op.execute(INTERNAL_SQL)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    # CREATE OR REPLACE keeps each function's identity, owner and privileges.
    op.execute(_replaced(RECORD, RECORD_REPLACEMENTS))
    op.execute(_replaced(RECORD_CREDIT_CUSTOMER, RECORD_CREDIT_CUSTOMER_REPLACEMENTS))
    op.execute(_replaced(CONFIRM, CONFIRM_REPLACEMENTS))


def downgrade() -> None:
    raise RuntimeError("Settlement returned Credit Refund migration is forward-only")
