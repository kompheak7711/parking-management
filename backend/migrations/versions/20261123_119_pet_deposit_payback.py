# ruff: noqa: E501
"""Pay back returned Pet Refund-review money after a pet noncompliance termination (V1-056 sub-slice 10c-2b-5).

BR-DEP-022, BR-SETTLE-008, BR-SETTLE-013, DL-032, DL-053; owner answer pay back to Q-2026-10-09-61,
owner answer (a) to Q-2026-10-10-73, owner answers (A) and (b) to Q-2026-10-10-75, owner answer (a)
to Q-2026-10-10-76:

- Money of a Pet Refund-review Refund (DL-053, always paid while the Lease is signed) that comes
  back to the Pet Deposit is the Customer's money, whether the return was verified before or after
  the termination (Q-75 (b)). Its amount is a running count over the Pet Deposit's history (Q-76
  (a)): a verified return adds returned money; a reversal of such a return and every later Pet
  Refund-review Refund take it out first. The pay-back value is the smaller of that count and what
  the Deposit holds; 0 for a Security Deposit. No other money adds to the count: a Settlement or
  correction Refund and its return change only what the Deposit holds, and a recovery by a charge
  (sub-slice 10e-1c) brings no money back.
- A Deposit with a forfeiture ground (BR-DEP-022) whose held money is above 0 and all pay-back
  money follows DL-032 (Q-75 (A)), also while its forfeiture stays active: before closure the
  Final Settlement applies it to the Lease's open debt in the DL-032 order and refunds the rest
  (BR-SETTLE-008); after closure every correction that runs the shared DL-032 step does the same.
  The Deposit is FORFEITURE_REQUIRED only while it holds money beyond the pay-back value.
- Approved tightening (Q-73 (a)): a Lease Deposit forfeiture takes only the held money beyond the
  pay-back value and is refused (22023) when nothing is beyond it.
- The returned-Refund correction with a new Refund checks the Deposit's path before the return is
  written; it also accepts a Pet Deposit whose held money after the return would be all pay-back
  money (a relaxing exception).

Three new internal functions (no grant); the Deposit path, the forfeiture source and the
returned-Refund plan are patched in place.
"""

from alembic import op
from sqlalchemy import text

revision = "20261123_119"
down_revision = "20261122_118"
branch_labels = None
depends_on = None

SQL = r"""
    -- Sub-slice 10c-2b-5 (owner answer (a) to Q-2026-10-10-76): the running count of a Pet
    -- Deposit's returned Pet Refund-review money. A verified return of a Pet Refund-review Refund
    -- adds what came back; a reversal of such a return and every Pet Refund-review Refund take it
    -- out first (never below 0). Only these rows count: a Settlement or correction Refund, its
    -- return and a recovery by a charge (RECOVERED_BY_CHARGE, no money came back) do not.
    CREATE FUNCTION app.lease_deposit_payback_count(p_deposit uuid)
    RETURNS bigint LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_count bigint:=0; v_event record;
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
            ORDER BY 1,2,3
        LOOP
            v_count:=GREATEST(0,v_count+v_event.delta);
        END LOOP;
        RETURN v_count;
    END $$;

    -- The pay-back value (owner answers to Q-2026-10-09-61, Q-2026-10-10-75 and Q-2026-10-10-76):
    -- the smaller of the running count and what the Pet Deposit holds; 0 for a Security Deposit
    -- and for an unknown Deposit (never NULL).
    CREATE FUNCTION app.lease_deposit_payback_value(p_deposit uuid)
    RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((SELECT CASE WHEN deposit.deposit_type='PET'
                THEN LEAST(app.lease_deposit_payback_count(deposit.id),
                    GREATEST(0,app.deposit_held_value_at(deposit.id,'infinity')))
                ELSE 0 END
            FROM app.deposits deposit WHERE deposit.id=p_deposit),0)
    $$;

    -- The returned-Refund correction checks the Deposit's path before the return is written
    -- (owner answer (A) to Q-2026-10-10-75 point 1): true when, after this return, the Pet Deposit
    -- holds money and every cent of it would be pay-back money (the count rises only when the
    -- returned Refund is a Pet Refund-review Refund; what the Deposit holds rises by the returned
    -- amount), which is exactly when its path is DL_032 once the return is in.
    CREATE FUNCTION app.lease_deposit_payback_after_return(p_deposit uuid, p_refund uuid, p_returned bigint)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE((SELECT p_returned>0
                AND app.deposit_held_value_at(deposit.id,'infinity')+p_returned>0
                AND app.lease_deposit_payback_count(deposit.id)
                    +CASE WHEN refund.pet_refund_review_id IS NOT NULL THEN p_returned ELSE 0 END
                    >=app.deposit_held_value_at(deposit.id,'infinity')+p_returned
            FROM app.deposits deposit
            JOIN app.refunds refund ON refund.id=p_refund AND refund.source_deposit_id=deposit.id
            WHERE deposit.id=p_deposit AND deposit.deposit_type='PET'),false)
    $$;
"""

INTERNAL = (
    "app.lease_deposit_payback_count(uuid)",
    "app.lease_deposit_payback_value(uuid)",
    "app.lease_deposit_payback_after_return(uuid,uuid,bigint)",
)

PATH = "app.lease_deposit_settlement_path(uuid,uuid)"
PATH_REPLACEMENTS = (
    (
        "        DECLARE v_ground text; v_forfeiture text;\n",
        "        DECLARE v_ground text; v_forfeiture text; v_held bigint; v_payback bigint;\n",
    ),
    (
        "            RETURN jsonb_build_object('ground',v_ground,'forfeiture',v_forfeiture,\n"
        "                'path',CASE WHEN v_forfeiture='ACTIVE' THEN 'KEPT'\n"
        "                    WHEN v_ground IS NULL OR v_forfeiture='REVERSED' THEN 'DL_032'\n"
        "                    WHEN app.deposit_held_value_at(p_deposit,'infinity')>0 THEN 'FORFEITURE_REQUIRED'\n",
        "            v_held:=app.deposit_held_value_at(p_deposit,'infinity');\n"
        "            -- Sub-slice 10c-2b-5 (pay back: owner answers to Q-2026-10-09-61, Q-2026-10-10-73 (a),\n"
        "            -- Q-2026-10-10-75 (A) and (b), Q-2026-10-10-76 (a)): returned Pet Refund-review money is\n"
        "            -- the Customer's. A Deposit with a forfeiture ground whose held money is all pay-back\n"
        "            -- money follows DL-032, also while its forfeiture stays active; it is\n"
        "            -- FORFEITURE_REQUIRED only while it holds money beyond the pay-back value.\n"
        "            v_payback:=app.lease_deposit_payback_value(p_deposit);\n"
        "            RETURN jsonb_build_object('ground',v_ground,'forfeiture',v_forfeiture,\n"
        "                'payback_usd_cents',v_payback,\n"
        "                'path',CASE WHEN v_ground IS NOT NULL AND v_held>0 AND v_payback=v_held THEN 'DL_032'\n"
        "                    WHEN v_forfeiture='ACTIVE' THEN 'KEPT'\n"
        "                    WHEN v_ground IS NULL OR v_forfeiture='REVERSED' THEN 'DL_032'\n"
        "                    WHEN v_held>0 THEN 'FORFEITURE_REQUIRED'\n",
    ),
)

FORFEITURE_SOURCE = "app.lease_deposit_forfeiture_source(uuid,uuid)"
FORFEITURE_SOURCE_REPLACEMENTS = (
    (
        "            v_held:=app.deposit_held_value_at(p_deposit,statement_timestamp());\n",
        "            -- Sub-slice 10c-2b-5 (owner answer (a) to Q-2026-10-10-73, approved tightening): the\n"
        "            -- forfeiture leaves out the pay-back money (returned Pet Refund-review money is the\n"
        "            -- Customer's); with nothing beyond it the Deposit holds nothing to forfeit.\n"
        "            v_held:=GREATEST(0,app.deposit_held_value_at(p_deposit,statement_timestamp())\n"
        "                -app.lease_deposit_payback_value(p_deposit));\n",
    ),
)

RETURN_PLAN = "app.settlement_refund_return_plan(uuid,uuid,jsonb)"
RETURN_PLAN_REPLACEMENTS = (
    (
        "            IF v_refund.source_deposit_id IS NOT NULL\n"
        "                AND app.lease_deposit_settlement_path(p_property,v_refund.source_deposit_id)->>'path'\n"
        "                    IS DISTINCT FROM 'DL_032'\n",
        "            IF v_refund.source_deposit_id IS NOT NULL\n"
        "                AND app.lease_deposit_settlement_path(p_property,v_refund.source_deposit_id)->>'path'\n"
        "                    IS DISTINCT FROM 'DL_032'\n"
        "                -- Sub-slice 10c-2b-5 (owner answer (A) to Q-2026-10-10-75 point 1): this check runs\n"
        "                -- before the return is written, so a Pet Deposit whose held money after this return\n"
        "                -- would be all pay-back money is accepted too (its path is DL_032 once the return is in).\n"
        "                AND NOT app.lease_deposit_payback_after_return(v_refund.source_deposit_id,v_refund.id,\n"
        "                    (p_input->>'returned_amount_usd_cents')::bigint)\n",
    ),
)

PATCHES = (
    (PATH, PATH_REPLACEMENTS),
    (FORFEITURE_SOURCE, FORFEITURE_SOURCE_REPLACEMENTS),
    (RETURN_PLAN, RETURN_PLAN_REPLACEMENTS),
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
            raise RuntimeError(f"Pet Deposit pay-back contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Pet Deposit pay-back migration is forward-only")
