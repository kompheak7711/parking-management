# ruff: noqa: E501
"""A forfeited right receipt keeps the Customer's pay-back money (V1-056 sub-slice 10e-2d).

BR-SETTLE-013, BR-SETTLE-008, DL-032, BR-DEP-022, BR-DEP-023; DB-SETTLE-005, DB-DEP-004; owner
answer (a) to Q-2026-10-12-93: a right receipt that a DEPOSIT_RECEIPT_CORRECTION forfeits (sub-slice
10e-2c) into a Pet Deposit with returned Pet Refund-review money is forfeited only beyond the
pay-back count; the rest stays in the Deposit as the Customer's pay-back money and follows DL-032 in
the same correction's plan (applied to debt, then refunded). Owner answer (b) to Q-2026-10-17-122:
the pay-back count holds only returned money the Customer has not received yet; money already paid
out (for example by the Final Settlement's Refund) is not paid back again; one rule on every path,
and where nothing was paid out the result stays as built.

- The running count of sub-slice 10c-2b-5 also takes out, first and in the same time order, every
  payout of the Deposit that is not undone: each Deposit application not reversed, and each other
  Refund of the Deposit less what came back to the Deposit for it (its Refund corrections: verified
  returns net of their reversals, and a recovery by a charge). The pay-back value, the Deposit path,
  the forfeiture source, the forfeiture insert check and the returned-Refund check follow it.
- The forfeiture list names the receipt less the smaller of the count and the receipt, and lists
  nothing when the count covers the receipt (a Deposit never forfeited then takes the whole receipt
  on the DL-032 path); a staff choice to forfeit again needs money beyond the count.
- The corrected receipt's own Deposit must end empty, so the correction undoes its payouts: its
  target count leaves the payouts out, the overlay names it, and the plan check uses the same count
  (a count that would still be too high fails closed at the confirm: the forfeiture writer's exact
  check and the step read the real count).
- The recorder passes each receipt's forfeited amount, and the overlay's `deposits_after` keeps the
  rest of the receipt in the plan.
- The plan check accepts a Pet Deposit with a forfeiture ground that holds, after the correction,
  only pay-back money (its path is DL_032 then, by the sub-slice 10c-2b-5 path rule); the
  confirm-time step reads the real path.
- The refusal of a forfeiture into a Deposit that would hold other money stays.

One new internal function (no grant) and exact-text patches: relaxing for the forfeiture rule (the
10e-2c pay-back refusal is replaced by it); the lower count narrows the returned-Refund exception
and the Pet Deposit's DL-032 path wherever pay-back money was paid out, as owner answer (b) to
Q-2026-10-17-122 orders (one rule on every path). The code of the forfeiture writer, the write
helper, the input, the pay-back limit of the forfeiture insert check and the Deposit path is
unchanged: at the write the Deposit holds the receipt, its pay-back value is the smaller of the
count and the receipt, so the writer's exact check equals the new amount.
"""

from alembic import op
from sqlalchemy import text

revision = "20261223_149"
down_revision = "20261222_148"
branch_labels = None
depends_on = None

SQL = r"""
    -- Sub-slice 10e-2d (owner answer (b) to Q-2026-10-17-122): the running pay-back count of
    -- sub-slice 10c-2b-5 holds only returned money the Customer has not received yet. As built, a
    -- verified return of a Pet Refund-review Refund adds what came back, and a reversal of such a
    -- return and every Pet Refund-review Refund take it out first (never below 0). Also taken out
    -- first, in the same time order, is every payout of the Deposit that is not undone: each
    -- Deposit application not reversed, and each other Refund of the Deposit less what came back
    -- to the Deposit for it (its Refund corrections: verified returns net of their reversals, and
    -- a recovery by a charge, which charges the money back). At the same moment returns come
    -- first. Forfeitures and their reversals are not payouts. p_returned_refund and p_returned
    -- count a return about to be written (a Pet Refund-review Refund's at the end; another
    -- Refund's lowers its net payout); p_without_payouts leaves every payout out (a receipt
    -- correction undoes every payout of its corrected receipt's Deposit).
    CREATE FUNCTION app.lease_deposit_payback_count_as(p_deposit uuid, p_returned_refund uuid,
        p_returned bigint, p_without_payouts boolean)
    RETURNS bigint LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_count bigint:=0; v_event record;
        v_returned bigint:=GREATEST(0,COALESCE(p_returned,0));
        v_payouts boolean:=NOT COALESCE(p_without_payouts,false);
    BEGIN
        FOR v_event IN
            SELECT refund.processed_at AS event_at,1 AS event_order,refund.id AS event_id,
                -refund.usd_accounting_value_cents AS delta
            FROM app.refunds refund
            WHERE refund.source_deposit_id=p_deposit AND refund.pet_refund_review_id IS NOT NULL
            UNION ALL
            SELECT correction.occurred_at,0,correction.id,correction.source_balance_effect_usd_cents
            FROM app.refund_corrections correction
            JOIN app.refunds refund ON refund.id=correction.refund_id
            LEFT JOIN app.refund_corrections returned ON returned.id=correction.reverses_correction_id
            WHERE refund.source_deposit_id=p_deposit AND refund.pet_refund_review_id IS NOT NULL
              AND ((correction.correction_kind='VALUE_CORRECTION'
                      AND correction.verified_return_amount_minor IS NOT NULL)
                  OR (correction.correction_kind='CORRECTION_REVERSAL'
                      AND returned.correction_kind='VALUE_CORRECTION'
                      AND returned.verified_return_amount_minor IS NOT NULL))
            UNION ALL
            SELECT 'infinity'::timestamptz,0,refund.id,v_returned
            FROM app.refunds refund
            WHERE refund.id=p_returned_refund AND refund.source_deposit_id=p_deposit
              AND refund.pet_refund_review_id IS NOT NULL AND v_returned>0
            UNION ALL
            SELECT application.occurred_at,2,application.id,-application.amount_usd_cents
            FROM app.deposit_applications application
            WHERE application.deposit_id=p_deposit AND v_payouts
              AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
                  WHERE reversal.deposit_application_id=application.id)
            UNION ALL
            SELECT refund.processed_at,2,refund.id,-LEAST(refund.usd_accounting_value_cents,
                GREATEST(0,refund.usd_accounting_value_cents
                    -COALESCE((SELECT sum(correction.source_balance_effect_usd_cents)
                        FROM app.refund_corrections correction
                        WHERE correction.refund_id=refund.id),0)::bigint
                    -CASE WHEN refund.id=p_returned_refund THEN v_returned ELSE 0 END))
            FROM app.refunds refund
            WHERE refund.source_deposit_id=p_deposit AND refund.pet_refund_review_id IS NULL
              AND v_payouts
            ORDER BY 1,2,3
        LOOP
            v_count:=GREATEST(0,v_count+v_event.delta);
        END LOOP;
        RETURN v_count;
    END $$;
"""

INTERNAL = ("app.lease_deposit_payback_count_as(uuid,uuid,bigint,boolean)",)

COUNT = "app.lease_deposit_payback_count(uuid)"
COUNT_REPLACEMENTS = (
    (
        "    DECLARE v_count bigint:=0; v_event record;\n"
        "    BEGIN\n"
        "        FOR v_event IN\n"
        "            SELECT refund.processed_at AS event_at,1 AS event_order,refund.id AS event_id,\n"
        "                -refund.usd_accounting_value_cents AS delta\n"
        "            FROM app.refunds refund\n"
        "            WHERE refund.source_deposit_id=p_deposit AND refund.pet_refund_review_id IS NOT NULL\n"
        "            UNION ALL\n"
        "            SELECT correction.occurred_at,0,correction.id,correction.source_balance_effect_usd_cents\n"
        "            FROM app.refund_corrections correction\n"
        "            JOIN app.refunds refund ON refund.id=correction.refund_id\n"
        "            LEFT JOIN app.refund_corrections returned ON returned.id=correction.reverses_correction_id\n"
        "            WHERE refund.source_deposit_id=p_deposit AND refund.pet_refund_review_id IS NOT NULL\n"
        "              AND ((correction.correction_kind='VALUE_CORRECTION'\n"
        "                      AND correction.verified_return_amount_minor IS NOT NULL)\n"
        "                  OR (correction.correction_kind='CORRECTION_REVERSAL'\n"
        "                      AND returned.correction_kind='VALUE_CORRECTION'\n"
        "                      AND returned.verified_return_amount_minor IS NOT NULL))\n"
        "            ORDER BY 1,2,3\n"
        "        LOOP\n"
        "            v_count:=GREATEST(0,v_count+v_event.delta);\n"
        "        END LOOP;\n"
        "        RETURN v_count;\n",
        "    BEGIN\n"
        "        -- Sub-slice 10e-2d (owner answer (b) to Q-2026-10-17-122): only returned money the\n"
        "        -- Customer has not received yet (app.lease_deposit_payback_count_as).\n"
        "        RETURN app.lease_deposit_payback_count_as(p_deposit,NULL,0,false);\n",
    ),
)

AFTER_RETURN = "app.lease_deposit_payback_after_return(uuid,uuid,bigint)"
AFTER_RETURN_REPLACEMENTS = (
    (
        "                AND app.lease_deposit_payback_count(deposit.id)\n"
        "                    +CASE WHEN refund.pet_refund_review_id IS NOT NULL THEN p_returned ELSE 0 END\n",
        "                -- Sub-slice 10e-2d (owner answer (b) to Q-2026-10-17-122): the count with this\n"
        "                -- return in (a Pet Refund-review Refund's adds it; another Refund's lowers its\n"
        "                -- payout, so a returned Settlement Refund's pay-back part counts again).\n"
        "                AND app.lease_deposit_payback_count_as(deposit.id,refund.id,p_returned,false)\n",
    ),
)

TARGETS = "app.settlement_deposit_receipt_correction_targets(uuid,jsonb,jsonb)"
TARGETS_REPLACEMENTS = (
    (
        "                'payback_count',CASE WHEN deposit.id IS NOT NULL\n"
        "                    THEN app.lease_deposit_payback_count(deposit.id) END,\n",
        "                -- Sub-slice 10e-2d (owner answer (b) to Q-2026-10-17-122): the corrected\n"
        "                -- receipt's own Deposit ends empty, so this correction undoes every payout of it.\n"
        "                'payback_count',CASE WHEN deposit.id IS NOT NULL\n"
        "                    THEN app.lease_deposit_payback_count_as(deposit.id,NULL,0,\n"
        "                        deposit.id IS NOT DISTINCT FROM (p_source->'receipt'->>'deposit_id')::uuid) END,\n",
    ),
)

FORFEITURES = "app.settlement_deposit_receipt_forfeitures(jsonb,text)"
FORFEITURES_REPLACEMENTS = (
    (
        "                'amount_usd_cents',(item.target->>'amount_usd_cents')::bigint,\n",
        "                -- Sub-slice 10e-2d (owner answer (a) to Q-2026-10-12-93): only the money beyond\n"
        "                -- the pay-back count; the rest follows DL-032 in the same correction's plan.\n"
        "                'amount_usd_cents',GREATEST(0,(item.target->>'amount_usd_cents')::bigint\n"
        "                    -COALESCE((item.target->>'payback_count')::bigint,0)),\n",
    ),
    (
        "          AND (item.target->'path'->>'forfeiture'='NONE' OR item.target->>'outcome'='FORFEIT')\n",
        "          AND (item.target->'path'->>'forfeiture'='NONE' OR item.target->>'outcome'='FORFEIT')\n"
        "          -- Sub-slice 10e-2d: nothing is listed when the count covers the receipt.\n"
        "          AND (item.target->>'amount_usd_cents')::bigint\n"
        "              >COALESCE((item.target->>'payback_count')::bigint,0)\n",
    ),
)

ALLOWED = "app.assert_settlement_deposit_receipt_targets_allowed(uuid,jsonb,jsonb)"
ALLOWED_REPLACEMENTS = (
    (
        "        -- Only the new receipt's money is forfeited: the Deposit holds nothing else after the\n"
        "        -- correction and has no pay-back count (Q-2026-10-12-93; refused until the owner answers).\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target\n"
        "            WHERE target->'path'->>'ground' IS NOT NULL\n"
        "              AND (target->'path'->>'forfeiture'='NONE' OR target->>'outcome'='FORFEIT')\n"
        "              AND (COALESCE((target->>'payback_count')::bigint,0)>0\n"
        "                  OR (target->>'deposit_id' IS DISTINCT FROM p_source->'receipt'->>'deposit_id'\n"
        "                      AND COALESCE((target->>'held_usd_cents')::bigint,0)<>0)))\n"
        "        THEN RAISE EXCEPTION 'A forfeiture in a receipt correction takes only the new receipt''s money'\n"
        "            USING ERRCODE='55000'; END IF;\n",
        "        -- Only the new receipt's money is forfeited: the Deposit holds nothing else after the\n"
        "        -- correction. Sub-slice 10e-2d (owner answer (a) to Q-2026-10-12-93): of that money, the\n"
        "        -- part within the pay-back count is the Customer's and follows DL-032; only the rest is\n"
        "        -- forfeited (app.settlement_deposit_receipt_forfeitures).\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target\n"
        "            WHERE target->'path'->>'ground' IS NOT NULL\n"
        "              AND (target->'path'->>'forfeiture'='NONE' OR target->>'outcome'='FORFEIT')\n"
        "              AND target->>'deposit_id' IS DISTINCT FROM p_source->'receipt'->>'deposit_id'\n"
        "              AND COALESCE((target->>'held_usd_cents')::bigint,0)<>0)\n"
        "        THEN RAISE EXCEPTION 'A forfeiture in a receipt correction takes only the new receipt''s money'\n"
        "            USING ERRCODE='55000'; END IF;\n"
        "        -- Sub-slice 10e-2d: a staff choice to forfeit again needs money beyond the pay-back count.\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target\n"
        "            WHERE target->'path'->>'ground' IS NOT NULL AND target->>'outcome'='FORFEIT'\n"
        "              AND (target->>'amount_usd_cents')::bigint\n"
        "                  <=COALESCE((target->>'payback_count')::bigint,0))\n"
        "        THEN RAISE EXCEPTION 'Nothing beyond the Customer''s pay-back money is left to forfeit; choose DL-032'\n"
        "            USING ERRCODE='55000'; END IF;\n",
    ),
)

OVERLAY = "app.settlement_deposit_receipt_correction_overlay(jsonb,jsonb)"
OVERLAY_REPLACEMENTS = (
    (
        "            'credits','{}'::jsonb,'deposits','{}'::jsonb,\n",
        "            'credits','{}'::jsonb,'deposits','{}'::jsonb,\n"
        "            -- Sub-slice 10e-2d (owner answer (b) to Q-2026-10-17-122): the plan check counts the\n"
        "            -- corrected receipt's own Deposit without its payouts (this correction undoes them).\n"
        "            'corrected_deposit_id',p_source->'receipt'->'deposit_id',\n",
    ),
    (
        "                    +COALESCE((SELECT sum((item->>'amount_usd_cents')::bigint)\n"
        "                        FROM jsonb_array_elements(p_receipts) item WHERE item->>'deposit_id'=deposit.id\n"
        "                          -- Sub-slice 10e-2c: forfeited money stays out of the plan.\n"
        "                          AND (item->'forfeit') IS DISTINCT FROM 'true'::jsonb),0))\n",
        "                    -- Sub-slice 10e-2c: forfeited money stays out of the plan; sub-slice 10e-2d:\n"
        "                    -- only the forfeited part of a receipt (its pay-back part follows DL-032).\n"
        "                    +COALESCE((SELECT sum((item->>'amount_usd_cents')::bigint\n"
        "                            -COALESCE((item->>'forfeit_usd_cents')::bigint,0))\n"
        "                        FROM jsonb_array_elements(p_receipts) item WHERE item->>'deposit_id'=deposit.id),0))\n",
    ),
)

RECORDER = (
    "app.record_settlement_deposit_receipt_correction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
)
RECORDER_REPLACEMENTS = (
    (
        "            v_overlay:=app.settlement_deposit_receipt_correction_overlay(v_source,\n"
        "                (SELECT jsonb_agg(item.value||jsonb_build_object('forfeit',v_forfeitures\n"
        "                        @> jsonb_build_array(jsonb_build_object('deposit_id',item.value->>'deposit_id')))\n"
        "                    ORDER BY item.position)\n",
        "            -- Sub-slice 10e-2d: each receipt carries its forfeited amount (only the money beyond\n"
        "            -- the pay-back count), so the overlay keeps the rest in the plan.\n"
        "            v_overlay:=app.settlement_deposit_receipt_correction_overlay(v_source,\n"
        "                (SELECT jsonb_agg(item.value||jsonb_build_object('forfeit_usd_cents',COALESCE((\n"
        "                        SELECT sum((forfeiture->>'amount_usd_cents')::bigint)\n"
        "                        FROM jsonb_array_elements(v_forfeitures) forfeiture\n"
        "                        WHERE forfeiture->>'deposit_id'=item.value->>'deposit_id'),0))\n"
        "                    ORDER BY item.position)\n",
    ),
)

PLAN_RESULT = "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)"
PLAN_RESULT_REPLACEMENTS = (
    (
        "                    WHERE key NOT IN ('pet_damage','hold_deposits','held_left','deposits_after',\n"
        "                        'new_obligations'))\n",
        "                    WHERE key NOT IN ('pet_damage','hold_deposits','held_left','deposits_after',\n"
        "                        'new_obligations','corrected_deposit_id'))\n",
    ),
    (
        "            -- Sub-slice 10e-2b-2: a receipt correction's placeholder lines (a line id to the\n",
        "            -- Sub-slice 10e-2d (owner answer (b) to Q-2026-10-17-122): a receipt correction's\n"
        "            -- corrected receipt's Deposit, a UUID string that deposits_after names.\n"
        "            OR (p_overlay ? 'corrected_deposit_id'\n"
        "                AND (jsonb_typeof(p_overlay->'corrected_deposit_id') IS DISTINCT FROM 'string'\n"
        "                    OR app.final_settlement_plan_id(p_overlay->'corrected_deposit_id')\n"
        "                        IS DISTINCT FROM p_overlay->>'corrected_deposit_id'\n"
        "                    OR jsonb_typeof(p_overlay->'deposits_after') IS DISTINCT FROM 'object'\n"
        "                    OR NOT (p_overlay->'deposits_after') ? (p_overlay->>'corrected_deposit_id')))\n"
        "            -- Sub-slice 10e-2b-2: a receipt correction's placeholder lines (a line id to the\n",
    ),
    (
        "            IF (v_entry.value#>>'{}')::bigint>0 AND v_item->>'path' IS DISTINCT FROM 'DL_032' THEN\n",
        "            IF (v_entry.value#>>'{}')::bigint>0 AND v_item->>'path' IS DISTINCT FROM 'DL_032'\n"
        "                -- Sub-slice 10e-2d (owner answer (a) to Q-2026-10-12-93): a Pet Deposit with a\n"
        "                -- forfeiture ground that holds only pay-back money after the correction follows\n"
        "                -- DL-032 then (the 10c-2b-5 path rule; the confirm-time step reads the real path);\n"
        "                -- the corrected receipt's own Deposit is counted without its payouts, which this\n"
        "                -- correction undoes (owner answer (b) to Q-2026-10-17-122).\n"
        "                -- A missing value refuses (round 2 security note: fail closed).\n"
        "                AND NOT COALESCE(v_item->>'deposit_type'='PET'\n"
        "                    AND app.lease_deposit_kept_rule(p_property,(v_entry.key)::uuid) IS NOT NULL\n"
        "                    AND (v_entry.value#>>'{}')::bigint\n"
        "                        <=app.lease_deposit_payback_count_as((v_entry.key)::uuid,NULL,0,\n"
        "                            COALESCE(v_entry.key=p_overlay->>'corrected_deposit_id',false)),false)\n"
        "            THEN\n",
    ),
)

PATCHES = (
    (COUNT, COUNT_REPLACEMENTS),
    (AFTER_RETURN, AFTER_RETURN_REPLACEMENTS),
    (TARGETS, TARGETS_REPLACEMENTS),
    (FORFEITURES, FORFEITURES_REPLACEMENTS),
    (ALLOWED, ALLOWED_REPLACEMENTS),
    (OVERLAY, OVERLAY_REPLACEMENTS),
    (RECORDER, RECORDER_REPLACEMENTS),
    (PLAN_RESULT, PLAN_RESULT_REPLACEMENTS),
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
            raise RuntimeError(
                f"Deposit receipt pay-back forfeiture contract changed: {signature}"
            )
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(SQL)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for signature, replacements in PATCHES:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("Deposit receipt pay-back forfeiture migration is forward-only")
