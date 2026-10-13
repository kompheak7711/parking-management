# ruff: noqa: E501
"""A return's money on a payment a later return reversal changed (V1-056 sub-slice 10e-3d-2b-1a).

BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, DL-032; DB-SETTLE-005; owner answer (a) to
Q-2026-10-13-100 point 1 (the reversal of a mistaken return makes the debt its money paid owed
again):

- New internal `app.settlement_returned_value_successor(p_kind, p_application)`: the active
  application that now holds an application's money that was not a reversed return's. While the
  application is active, it is the application itself. When a `RETURN_REVERSAL` reversed it and
  put back the rest (its stored source lists the application in `reapply`), it is that put-back:
  the n-th entry of the source's `reapply` is the n-th application the confirm linked to that
  correction. The put-back is checked (the same Credit or Deposit, the same obligation, the same
  stage for a Deposit, the entry's amount, less than the application) and followed again while a
  later return reversal changed it too. Any other change (a `REFUND` correction's release, a
  pet-damage reclassification, a reversal without a put-back) or a put-back that does not check
  gives NULL (fail closed; Q-2026-10-13-107 for those changes). Review round 1: the reversing
  correction and the put-back belong to the application's own Final Settlement, the source lists
  the application exactly once, and a Credit application has exactly one detail on each side.
- A return reversal's put-back is the reversed application less exactly that return's part, so
  every other return's part in it is in the put-back with the same amount. In
  `app.settlement_return_reversal_source_state` (exact-text patch) a part of the earlier
  correction's money that another correction paid out on an application changed that way now
  follows to the put-back: the put-back is reversed whole and its rest put back, as for any other
  application part (sub-slice 10e-3d-2a). A part whose successor is NULL or smaller than the part
  stays open with the sub-slice 10e-3d-2b message.

No check, writer, lock or grant changes. A `RETURN_REVERSAL` draft recorded before this migration
whose source now differs is stale at its confirm (P5S02); staff reject it and record it again.
"""

from alembic import op
from sqlalchemy import text

revision = "20261205_131"
down_revision = "20261204_130"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    -- Sub-slice 10e-3d-2b-1a: the active application now holding p_application's money that was
    -- not a reversed return's: the application itself while it is active; after a RETURN_REVERSAL
    -- reversed it and put back the rest, that put-back (followed again while a later return
    -- reversal changed it too). NULL for any other change, or when the put-back does not check
    -- (fail closed).
    CREATE FUNCTION app.settlement_returned_value_successor(p_kind text,p_application uuid)
    RETURNS uuid LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE
        v_current uuid:=p_application; v_correction uuid; v_source jsonb; v_entry jsonb;
        v_position integer; v_next uuid; v_steps integer:=0; v_line uuid; v_next_line uuid;
        v_credit app.customer_credit_applications%ROWTYPE;
        v_deposit app.deposit_applications%ROWTYPE;
    BEGIN
        IF p_kind IS NULL OR p_kind NOT IN ('CREDIT','DEPOSIT') OR p_application IS NULL THEN
            RETURN NULL; END IF;
        LOOP
            v_correction:=NULL; v_source:=NULL; v_entry:=NULL; v_next:=NULL;
            IF p_kind='CREDIT' THEN
                SELECT * INTO v_credit FROM app.customer_credit_applications WHERE id=v_current;
                IF NOT FOUND THEN RETURN NULL; END IF;
                IF NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals reversal
                    WHERE reversal.credit_application_id=v_current) THEN RETURN v_current; END IF;
                SELECT effect.settlement_correction_id INTO v_correction
                FROM app.customer_credit_application_reversals reversal
                JOIN app.settlement_correction_effects effect
                    ON effect.credit_application_reversal_id=reversal.id
                WHERE reversal.credit_application_id=v_current;
            ELSE
                SELECT * INTO v_deposit FROM app.deposit_applications WHERE id=v_current;
                IF NOT FOUND THEN RETURN NULL; END IF;
                IF NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
                    WHERE reversal.deposit_application_id=v_current) THEN RETURN v_current; END IF;
                SELECT effect.settlement_correction_id INTO v_correction
                FROM app.deposit_application_reversals reversal
                JOIN app.settlement_correction_effects effect
                    ON effect.deposit_application_reversal_id=reversal.id
                WHERE reversal.deposit_application_id=v_current;
            END IF;
            v_steps:=v_steps+1;
            IF v_correction IS NULL OR v_steps>100 THEN RETURN NULL; END IF;
            -- Only a return reversal's put-back carries the other money on unchanged; review round
            -- 1: a correction of the application's own Final Settlement.
            SELECT draft.payload->'source' INTO v_source
            FROM app.settlement_corrections correction
            JOIN app.financial_drafts draft ON draft.id=correction.correlation_id
                AND draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='RETURN_REVERSAL'
            WHERE correction.id=v_correction
              AND correction.final_settlement_id=CASE WHEN p_kind='CREDIT'
                  THEN v_credit.final_settlement_id ELSE v_deposit.final_settlement_id END;
            IF v_source IS NULL THEN RETURN NULL; END IF;
            -- Review round 1: exactly one entry for the application.
            IF (SELECT count(*) FROM jsonb_array_elements(CASE WHEN jsonb_typeof(v_source->'reapply')='array'
                    THEN v_source->'reapply' ELSE '[]'::jsonb END) item
                WHERE item->>'application_id'=v_current::text)<>1
            THEN RETURN NULL; END IF;
            SELECT entry.item,entry.position::integer INTO v_entry,v_position
            FROM jsonb_array_elements(CASE WHEN jsonb_typeof(v_source->'reapply')='array'
                THEN v_source->'reapply' ELSE '[]'::jsonb END) WITH ORDINALITY entry(item,position)
            WHERE entry.item->>'application_id'=v_current::text AND entry.item->>'source_kind'=p_kind;
            IF v_entry IS NULL THEN RETURN NULL; END IF;
            -- The confirm writes the n-th entry as the n-th application linked to the correction.
            SELECT COALESCE(linked.customer_credit_application_id,linked.deposit_application_id)
                INTO v_next
            FROM (SELECT effect.customer_credit_application_id,effect.deposit_application_id,
                    row_number() OVER (ORDER BY effect.effect_sequence) AS rank
                FROM app.settlement_correction_effects effect
                WHERE effect.settlement_correction_id=v_correction
                  AND (effect.customer_credit_application_id IS NOT NULL
                      OR effect.deposit_application_id IS NOT NULL)) linked
            WHERE linked.rank=v_position;
            IF v_next IS NULL THEN RETURN NULL; END IF;
            -- The same source and obligation (and stage), the entry's amount, less than before;
            -- review round 1: the same Final Settlement, and a Credit application with exactly one
            -- detail on each side.
            IF p_kind='CREDIT' THEN
                IF (SELECT count(*) FROM app.customer_credit_application_details detail
                        WHERE detail.customer_credit_application_id=v_current)<>1
                    OR (SELECT count(*) FROM app.customer_credit_application_details detail
                        WHERE detail.customer_credit_application_id=v_next)<>1
                THEN RETURN NULL; END IF;
                SELECT detail.invoice_line_id INTO v_line
                FROM app.customer_credit_application_details detail
                WHERE detail.customer_credit_application_id=v_current;
                SELECT detail.invoice_line_id INTO v_next_line
                FROM app.customer_credit_application_details detail
                WHERE detail.customer_credit_application_id=v_next;
                IF v_next_line IS DISTINCT FROM v_line
                    OR NOT EXISTS(SELECT 1 FROM app.customer_credit_applications successor
                        WHERE successor.id=v_next
                          AND successor.final_settlement_id=v_credit.final_settlement_id
                          AND successor.customer_credit_id=v_credit.customer_credit_id
                          AND successor.target_kind=v_credit.target_kind
                          AND successor.invoice_id IS NOT DISTINCT FROM v_credit.invoice_id
                          AND successor.late_payment_charge_id
                              IS NOT DISTINCT FROM v_credit.late_payment_charge_id
                          AND successor.amount_usd_cents::text=v_entry->>'amount_usd_cents'
                          AND successor.amount_usd_cents<v_credit.amount_usd_cents)
                THEN RETURN NULL; END IF;
            ELSIF NOT EXISTS(SELECT 1 FROM app.deposit_applications successor
                WHERE successor.id=v_next AND successor.deposit_id=v_deposit.deposit_id
                  AND successor.final_settlement_id=v_deposit.final_settlement_id
                  AND successor.application_stage=v_deposit.application_stage
                  AND successor.target_kind=v_deposit.target_kind
                  AND successor.invoice_id IS NOT DISTINCT FROM v_deposit.invoice_id
                  AND successor.invoice_line_id IS NOT DISTINCT FROM v_deposit.invoice_line_id
                  AND successor.late_payment_charge_id
                      IS NOT DISTINCT FROM v_deposit.late_payment_charge_id
                  AND successor.amount_usd_cents::text=v_entry->>'amount_usd_cents'
                  AND successor.amount_usd_cents<v_deposit.amount_usd_cents)
            THEN RETURN NULL;
            END IF;
            v_current:=v_next;
        END LOOP;
    END $$;
"""

INTERNAL = ("app.settlement_returned_value_successor(text,uuid)",)

SOURCE = "app.settlement_return_reversal_source_state(uuid,uuid)"
SOURCE_REPLACEMENTS = (
    (
        """        -- A part this reversal cannot undo yet is open, with its kind: a payment a later
        -- correction changed (an application reversed since, or a Refund part more than the
        -- Refund's net), or the take of a correction that also reversed the Credit, a return or
        -- a receipt, or forfeited.""",
        """        -- A part this reversal cannot undo yet is open, with its kind: a payment a later
        -- correction changed (an application reversed since, unless a return reversal put its
        -- rest back: sub-slice 10e-3d-2b-1a below; or a Refund part more than the Refund's net),
        -- or the take of a correction that also reversed the Credit, a return or a receipt, or
        -- forfeited.""",
    ),
    (
        """        ), swept_state AS (
            SELECT taken.*,CASE
                    WHEN taken.record_kind NOT IN ('REFUND','CREDIT_APPLICATION','DEPOSIT_APPLICATION')
                        THEN taken.record_kind
                    WHEN taken.record_kind='CREDIT_APPLICATION' AND EXISTS(SELECT 1
                        FROM app.customer_credit_application_reversals reversal
                        WHERE reversal.credit_application_id=taken.record_id)
                        THEN 'CHANGED_APPLICATION'
                    WHEN taken.record_kind='DEPOSIT_APPLICATION' AND EXISTS(SELECT 1
                        FROM app.deposit_application_reversals reversal
                        WHERE reversal.deposit_application_id=taken.record_id)
                        THEN 'CHANGED_APPLICATION'
                    WHEN taken.record_kind='REFUND' AND NOT COALESCE(taken.part_usd_cents
                        <=app.refund_net_value_at(taken.record_id,'infinity'),false)
                        THEN 'CHANGED_REFUND' END AS open_kind
            FROM earlier
            CROSS JOIN LATERAL app.settlement_returned_value_takes(p_settlement,
                CASE WHEN earlier.deposit_id IS NOT NULL THEN 'DEPOSIT' ELSE 'CREDIT' END,
                COALESCE(earlier.deposit_id,earlier.credit_id),earlier.id) taken
""",
        """        -- Sub-slice 10e-3d-2b-1a (owner answer (a) to Q-2026-10-13-100 point 1): an application
        -- part follows to the application now holding it (app.settlement_returned_value_successor:
        -- itself while active, else the put-back of the return reversal that changed it), with
        -- that application's correction and amount; it is open when there is none or the part is
        -- more than it.
        ), swept_state AS (
            SELECT COALESCE(followed.correction_id,taken.settlement_correction_id)
                    AS settlement_correction_id,
                taken.record_kind,COALESCE(followed.id,taken.record_id) AS record_id,
                COALESCE(followed.amount,taken.amount_usd_cents)::bigint AS amount_usd_cents,
                taken.part_usd_cents,CASE
                    WHEN taken.record_kind NOT IN ('REFUND','CREDIT_APPLICATION','DEPOSIT_APPLICATION')
                        THEN taken.record_kind
                    WHEN taken.record_kind IN ('CREDIT_APPLICATION','DEPOSIT_APPLICATION')
                        AND NOT COALESCE(followed.amount>=taken.part_usd_cents,false)
                        THEN 'CHANGED_APPLICATION'
                    WHEN taken.record_kind='REFUND' AND NOT COALESCE(taken.part_usd_cents
                        <=app.refund_net_value_at(taken.record_id,'infinity'),false)
                        THEN 'CHANGED_REFUND' END AS open_kind
            FROM earlier
            CROSS JOIN LATERAL app.settlement_returned_value_takes(p_settlement,
                CASE WHEN earlier.deposit_id IS NOT NULL THEN 'DEPOSIT' ELSE 'CREDIT' END,
                COALESCE(earlier.deposit_id,earlier.credit_id),earlier.id) taken
            LEFT JOIN LATERAL (
                SELECT successor.id,COALESCE(credit_now.amount_usd_cents,deposit_now.amount_usd_cents)
                        AS amount,
                    owner.settlement_correction_id AS correction_id
                FROM (SELECT app.settlement_returned_value_successor(CASE taken.record_kind
                        WHEN 'CREDIT_APPLICATION' THEN 'CREDIT' ELSE 'DEPOSIT' END,
                        taken.record_id) AS id) successor
                LEFT JOIN app.customer_credit_applications credit_now
                    ON taken.record_kind='CREDIT_APPLICATION' AND credit_now.id=successor.id
                LEFT JOIN app.deposit_applications deposit_now
                    ON taken.record_kind='DEPOSIT_APPLICATION' AND deposit_now.id=successor.id
                LEFT JOIN app.settlement_correction_effects owner
                    ON owner.customer_credit_application_id=successor.id
                    OR owner.deposit_application_id=successor.id
                WHERE taken.record_kind IN ('CREDIT_APPLICATION','DEPOSIT_APPLICATION')
                  AND successor.id IS NOT NULL) followed ON true
""",
    ),
)

PATCHES = ((SOURCE, SOURCE_REPLACEMENTS),)


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
                f"Settlement return reversal successor contract changed: {signature}"
            )
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(FUNCTION_SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Settlement return reversal successor migration is forward-only")
