# ruff: noqa: E501
"""A return's money on a payment that another Lease's REFUND correction changed is followed into
that correction's Refunds and payments and undone through the companion (V1-056 sub-slice
10e-3d-2d-2b-2).

BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014; DB-SETTLE-005, DB-REFUND-002; owner answers (a) to
Q-2026-10-13-103 point 3 and Q-2026-10-13-107, owner answer 4 of 2026-10-16 (a charge-back of the
other Lease's Refund goes on that Lease when its recipient is that Lease's signed Customer). Until
now the follow function read a changing correction only of this Final Settlement, so a stretch of
a return's money on a payment that a correction of another Final Settlement B reversed stopped
open (`CHANGED_APPLICATION`, set-up R1 of the 10e-3d-2d-2b-1 review record).

- `app.settlement_returned_value_follow` (exact-text patch): the changing correction's draft is
  read also for a correction of another Final Settlement when the source is a Credit and its
  variant is `REFUND` (an allow-list); its Refunds and payments are then followed exactly as a
  `REFUND` correction's of this Settlement (owner answer (a) to Q-2026-10-13-107). Every other
  correction of another Settlement still stops open.
- New internal `app.settlement_refund_owner(uuid)`: the Final Settlement of the correction a Refund
  is linked to.
- `app.settlement_return_reversal_source_state` (exact-text patches): a Refund part's charge-back
  goes on the Lease of the Final Settlement whose correction holds the part when the recipient is
  its signed Customer, else on no Lease; the recovery entry names that Lease's Final Settlement;
  `companions` also lists each other Settlement that owns a Refund part.
- `app.settlement_return_reversal_companion_source` (exact-text patch): new key `recoveries`, the
  charge-backs of that Settlement's Refunds.
- `app.assert_settlement_return_reversal_allowed` (exact-text patches): the companions also match
  the owners of the Refund parts; a charge-back of another Settlement's Refund belongs to a listed
  companion and names that Settlement and its Lease, or no Lease and no Settlement (fail closed);
  the `OTHER_SETTLEMENT` message is reworded (a part on another Settlement's Refund reached
  through a take stays refused; no real path found).
- `app.confirm_settlement_return_reversal` (exact-text patches): the charge-backs of another
  Settlement's Refunds are written linked to that Settlement's companion (its closed-Settlement
  guards then accept the charge on its Lease); the companion's audit event names them.
- `app.refund_recovery_allowed` and `app.settlement_return_reversal_refund` (exact-text patches):
  a charge-back linked to a companion confirmed in this transaction is allowed when its return
  reversal, confirmed in this transaction too, lists the Refund; a row linked to the reversal
  alone stays refused (every closed Final Settlement the Refund belongs to must link it, and the
  reversal's own branch takes only a Refund of no other Settlement).
- `app.settlement_return_reversal_recovery_amount` (exact-text patch): a charge-back linked to a
  companion recovers the amount the companion's draft lists (a share of the Refund's net, as a
  return reversal's own charge-back).
- `app.settlement_return_reversal_result` (exact-text patch): each companion names its
  charge-backs.

No table, column, constraint, trigger or lock change; no new grant. A `RETURN_REVERSAL` draft
recorded before this migration whose source now differs is stale at its confirm (P5S02); staff
reject it and record it again.
"""

from alembic import op
from sqlalchemy import text

revision = "20261214_140"
down_revision = "20261213_139"
branch_labels = None
depends_on = None

REFUND_OWNER = "app.settlement_refund_owner(uuid)"

FUNCTION_SQL = """
    -- The Final Settlement of the correction a Refund is linked to; NULL when none.
    CREATE FUNCTION app.settlement_refund_owner(p_refund uuid)
    RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT correction.final_settlement_id
        FROM app.settlement_correction_effects effect
        JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
        WHERE effect.refund_id=p_refund
    $$;
"""

FOLLOW = "app.settlement_returned_value_follow(uuid,text,uuid,text,uuid,bigint,bigint,uuid)"
FOLLOW_REPLACEMENTS = (
    (
        """
            WHERE correction.id=v_changer AND correction.final_settlement_id=p_settlement;""",
        """
            WHERE correction.id=v_changer AND (correction.final_settlement_id=p_settlement
                -- Sub-slice 10e-3d-2d-2b-2 (owner answers (a) to Q-2026-10-13-103 point 3 and
                -- Q-2026-10-13-107, owner answer 4 of 2026-10-16): or a REFUND correction of
                -- another Final Settlement that changed a Credit payment (an allow-list); its
                -- Refund parts are charged back and its payment parts undone through a companion
                -- correction of that Settlement.
                OR (p_kind='CREDIT' AND draft.payload->>'variant'='REFUND'));""",
        1,
    ),
)

STATE = "app.settlement_return_reversal_source_state(uuid,uuid)"
STATE_REPLACEMENTS = (
    (
        """
        ), swept_paid AS (
            -- The recovery entry of a Refund part, as the own uses' entries below.
            SELECT refund.*,app.refund_net_value_at(refund.id,'infinity') AS net,
                CASE WHEN refund.source_deposit_id IS NULL THEN 'CREDIT' ELSE 'DEPOSIT' END AS source_kind,
                COALESCE(refund.source_deposit_id,refund.source_customer_credit_id) AS source_id,
                CASE WHEN EXISTS(SELECT 1 FROM app.lease_signers signer
                    WHERE signer.lease_id=(SELECT settlement.lease_id FROM settlement)
                      AND signer.customer_id=refund.recipient_customer_id
                      AND signer.signed_at IS NOT NULL)
                    THEN (SELECT settlement.lease_id FROM settlement) END AS lease_id,""",
        """
        ), swept_paid AS (
            -- The recovery entry of a Refund part, as the own uses' entries below.
            -- Sub-slice 10e-3d-2d-2b-2 (owner answer 4 of 2026-10-16): on the Lease of the Final
            -- Settlement whose correction holds the part (another Lease's for a part of another
            -- Settlement's REFUND correction) when the recipient is its signed Customer.
            SELECT refund.*,app.refund_net_value_at(refund.id,'infinity') AS net,
                CASE WHEN refund.source_deposit_id IS NULL THEN 'CREDIT' ELSE 'DEPOSIT' END AS source_kind,
                COALESCE(refund.source_deposit_id,refund.source_customer_credit_id) AS source_id,
                CASE WHEN EXISTS(SELECT 1 FROM app.lease_signers signer
                    WHERE signer.lease_id=holder.lease_id
                      AND signer.customer_id=refund.recipient_customer_id
                      AND signer.signed_at IS NOT NULL)
                    THEN holder.lease_id END AS lease_id,""",
        1,
    ),
    (
        """
            FROM swept_undone taken JOIN app.refunds refund ON refund.id=taken.record_id
            WHERE taken.record_kind='REFUND'""",
        """
            FROM swept_undone taken JOIN app.refunds refund ON refund.id=taken.record_id
            JOIN app.settlement_corrections holding ON holding.id=taken.settlement_correction_id
            JOIN app.final_settlements holder ON holder.id=holding.final_settlement_id
            WHERE taken.record_kind='REFUND'""",
        1,
    ),
    (
        """
                WHERE other.id<>p_settlement AND other.id IN (SELECT
                        app.settlement_credit_application_owner(taken.record_id)
                    FROM swept_undone taken WHERE taken.record_kind='CREDIT_APPLICATION')),""",
        """
                WHERE other.id<>p_settlement AND other.id IN (SELECT
                        app.settlement_credit_application_owner(taken.record_id)
                    FROM swept_undone taken WHERE taken.record_kind='CREDIT_APPLICATION'
                    -- Sub-slice 10e-3d-2d-2b-2: or whose correction's Refund part it charges back.
                    UNION ALL
                    SELECT app.settlement_refund_owner(taken.record_id)
                    FROM swept_undone taken WHERE taken.record_kind='REFUND')),""",
        1,
    ),
    (
        """
                    'closed_final_settlement_id',CASE WHEN paid.lease_id IS NOT NULL THEN p_settlement END,""",
        """
                    -- Sub-slice 10e-3d-2d-2b-2: the Final Settlement of the charged Lease (one per
                    -- Lease; this Settlement's, or another's for its correction's Refund).
                    'closed_final_settlement_id',(SELECT closed.id FROM app.final_settlements closed
                        WHERE closed.lease_id=paid.lease_id),""",
        1,
    ),
)

COMPANION_SOURCE = "app.settlement_return_reversal_companion_source(jsonb,uuid)"
COMPANION_SOURCE_REPLACEMENTS = (
    (
        """
                  AND app.settlement_credit_application_owner((entry.item->>'application_id')::uuid)
                      =p_settlement))""",
        """
                  AND app.settlement_credit_application_owner((entry.item->>'application_id')::uuid)
                      =p_settlement),
            -- Sub-slice 10e-3d-2d-2b-2: the charge-backs of that Settlement's Refunds.
            'recoveries',(SELECT COALESCE(jsonb_agg(entry.item ORDER BY entry.position),'[]'::jsonb)
                FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_source->'recoveries')='array'
                    THEN p_source->'recoveries' ELSE '[]'::jsonb END) WITH ORDINALITY entry(item,position)
                WHERE app.settlement_refund_owner((entry.item->>'refund_id')::uuid)=p_settlement))""",
        1,
    ),
)

ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"
ASSERT_REPLACEMENTS = (
    (
        """
        THEN RAISE EXCEPTION 'A correction of another Lease''s Final Settlement used this return''s money; reversing it waits for sub-slice 10e-3d-2d-2'""",
        """
        -- Sub-slice 10e-3d-2d-2b-2: such a part now stands only for a part on another
        -- Settlement's Refund reached through a take (no real path found).
        THEN RAISE EXCEPTION 'A correction of another Lease''s Final Settlement used this return''s money in a way this reversal cannot undo; reversing it waits for the owner'""",
        1,
    ),
    (
        """
                    FROM jsonb_array_elements(p_source->'credit_applications') item
                    JOIN app.customer_credit_applications application
                        ON application.id::text=item->>'id'
                    -- Review round 1: an ordinary application (no Final Settlement of its own)
                    -- belongs to the Final Settlement of its target's Lease; one with neither is
                    -- refused here.
                    CROSS JOIN LATERAL (SELECT
                        app.settlement_credit_application_owner(application.id)::text AS owner) owned
                    WHERE owned.owner IS DISTINCT FROM p_source->'settlement'->>'id')
        THEN RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;""",
        """
                    -- Review round 1: an ordinary application (no Final Settlement of its own)
                    -- belongs to the Final Settlement of its target's Lease; one with neither is
                    -- refused here.
                    FROM (SELECT app.settlement_credit_application_owner(application.id)::text AS owner
                        FROM jsonb_array_elements(p_source->'credit_applications') item
                        JOIN app.customer_credit_applications application
                            ON application.id::text=item->>'id'
                        -- Sub-slice 10e-3d-2d-2b-2: and the Final Settlement of each Refund part's
                        -- correction (a Refund linked to no correction is not another Settlement's).
                        UNION ALL
                        SELECT app.settlement_refund_owner(refund.id)::text
                        FROM jsonb_array_elements((p_source->'swept')||CASE WHEN v_walk
                            THEN p_source->'own_parts' ELSE '[]'::jsonb END) item
                        JOIN app.refunds refund ON refund.id::text=item->>'record_id'
                        WHERE item->>'record_kind'='REFUND'
                          AND app.settlement_refund_owner(refund.id) IS NOT NULL) owned
                    WHERE owned.owner IS DISTINCT FROM p_source->'settlement'->>'id')
        THEN RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;
        -- Sub-slice 10e-3d-2d-2b-2 (owner answer 4 of 2026-10-16): a charge-back of another Final
        -- Settlement's Refund belongs to a listed companion (the confirm writes it through that
        -- companion only) and is charged on that Settlement's Lease, named by that Settlement, or
        -- on no Lease (fail closed; security review round 1).
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source->'recoveries') recovery
            CROSS JOIN LATERAL (SELECT
                app.settlement_refund_owner((recovery->>'refund_id')::uuid)::text AS owner) owned
            WHERE owned.owner IS NOT NULL
              AND owned.owner IS DISTINCT FROM p_source->'settlement'->>'id'
              AND recovery->>'refund_id' IS DISTINCT FROM p_source->'earlier'->>'refund_id'
              AND (NOT EXISTS(SELECT 1 FROM jsonb_array_elements(CASE
                          WHEN jsonb_typeof(p_source->'companions')='array'
                          THEN p_source->'companions' ELSE '[]'::jsonb END) companion
                      WHERE companion->>'final_settlement_id'=owned.owner)
                  OR recovery->>'closed_final_settlement_id' IS DISTINCT FROM CASE
                      WHEN recovery->>'lease_id' IS NOT NULL THEN owned.owner END
                  OR (recovery->>'lease_id' IS NOT NULL
                      AND recovery->>'lease_id' IS DISTINCT FROM (SELECT other.lease_id::text
                          FROM app.final_settlements other WHERE other.id::text=owned.owner))))
        THEN RAISE EXCEPTION 'The return reversal source is incomplete' USING ERRCODE='55000'; END IF;""",
        1,
    ),
)

CONFIRM = "app.confirm_settlement_return_reversal(uuid,uuid,uuid,text)"
CONFIRM_REPLACEMENTS = (
    (
        """
                WHERE entry.item->>'refund_id' IS DISTINCT FROM v_source->'earlier'->>'refund_id'),
            v_draft.reason,v_input->>'evidence_reference',v_at,v_evidence);""",
        """
                WHERE entry.item->>'refund_id' IS DISTINCT FROM v_source->'earlier'->>'refund_id'
                  -- Sub-slice 10e-3d-2d-2b-2: not another Final Settlement's Refund (below).
                  AND COALESCE(app.settlement_refund_owner((entry.item->>'refund_id')::uuid),
                      v_settlement.id)=v_settlement.id),
            v_draft.reason,v_input->>'evidence_reference',v_at,v_evidence);
        -- Sub-slice 10e-3d-2d-2b-2 (owner answer 4 of 2026-10-16): the charge-backs of another
        -- Final Settlement's Refunds, in Settlement id order, each linked to that Settlement's
        -- companion, so its closed-Settlement guards accept the charge on its Lease.
        FOR v_companion IN SELECT item FROM jsonb_array_elements(v_source->'companions') item
            ORDER BY item->>'final_settlement_id'
        LOOP
            v_other:=(v_companion->>'final_settlement_id')::uuid;
            IF EXISTS(SELECT 1 FROM jsonb_array_elements(v_source->'recoveries') item
                WHERE item->>'refund_id' IS DISTINCT FROM v_source->'earlier'->>'refund_id'
                  AND app.settlement_refund_owner((item->>'refund_id')::uuid)=v_other) THEN
                v_at:=app.write_payment_return_recoveries(p_property,p_actor,p_draft,
                    (v_companions->>v_other::text)::uuid,NULL,
                    (SELECT jsonb_agg(entry.item ORDER BY entry.position)
                        FROM jsonb_array_elements(v_source->'recoveries') WITH ORDINALITY entry(item,position)
                        WHERE entry.item->>'refund_id' IS DISTINCT FROM v_source->'earlier'->>'refund_id'
                          AND app.settlement_refund_owner((entry.item->>'refund_id')::uuid)=v_other),
                    v_draft.reason,v_input->>'evidence_reference',v_at,
                    v_evidence||jsonb_build_object('companion_settlement_correction_id',
                        (v_companions->>v_other::text)::uuid));
            END IF;
        END LOOP;""",
        1,
    ),
    (
        """
                    'reapplied',v_companion->'reapplied'),""",
        """
                    'reapplied',v_companion->'reapplied',
                    -- Sub-slice 10e-3d-2d-2b-2: its charge-backs of that Settlement's Refunds.
                    'recoveries',v_companion->'recoveries'),""",
        1,
    ),
)

RESULT = "app.settlement_return_reversal_result(uuid)"
RESULT_REPLACEMENTS = (
    (
        """
                        WHERE effect.settlement_correction_id=companion.id))
                    ORDER BY companion.final_settlement_id),'[]'::jsonb)""",
        """
                        WHERE effect.settlement_correction_id=companion.id),
                    -- Sub-slice 10e-3d-2d-2b-2: its charge-backs of that Settlement's Refunds.
                    'recoveries',(SELECT COALESCE(jsonb_agg(app.refund_recovery_json(recovery.id)
                            ORDER BY effect.effect_sequence),'[]'::jsonb)
                        FROM app.settlement_correction_effects effect
                        JOIN app.refund_corrections recovery ON recovery.id=effect.refund_correction_id
                        WHERE effect.settlement_correction_id=companion.id
                          AND recovery.correction_kind='RECOVERED_BY_CHARGE'))
                    ORDER BY companion.final_settlement_id),'[]'::jsonb)""",
        1,
    ),
)

REVERSAL_REFUND = "app.settlement_return_reversal_refund(uuid,uuid)"
REVERSAL_REFUND_REPLACEMENTS = (
    (
        """
                            AND other.final_settlement_id::text=draft.payload->>'final_settlement_id'))""",
        """
                            AND (other.final_settlement_id::text=draft.payload->>'final_settlement_id'
                                -- Sub-slice 10e-3d-2d-2b-2: or another Final Settlement's
                                -- correction whose Settlement the source names as a companion
                                -- (the charge-back is linked to that companion).
                                OR EXISTS(SELECT 1 FROM jsonb_array_elements(CASE
                                        WHEN jsonb_typeof(draft.payload->'source'->'companions')='array'
                                        THEN draft.payload->'source'->'companions' ELSE '[]'::jsonb END) companion
                                    WHERE companion->>'final_settlement_id'=other.final_settlement_id::text))))""",
        1,
    ),
)

RECOVERY_ALLOWED = "app.refund_recovery_allowed(app.refund_corrections)"
RECOVERY_ALLOWED_REPLACEMENTS = (
    (
        """
                          AND app.settlement_return_reversal_refund(draft.id,refund.id)))""",
        """
                          AND app.settlement_return_reversal_refund(draft.id,refund.id)
                          -- Sub-slice 10e-3d-2d-2b-2 (security review round 2): a Refund of
                          -- another Final Settlement only through that Settlement's companion.
                          AND COALESCE(app.settlement_refund_owner(refund.id)::text,
                              draft.payload->>'final_settlement_id')
                              =draft.payload->>'final_settlement_id')
                    -- Sub-slice 10e-3d-2d-2b-2 (owner answer 4 of 2026-10-16): or inside a
                    -- RETURN_REVERSAL_COMPANION of the Refund's own Final Settlement, confirmed by
                    -- the same approver in this transaction, that links the row, whose return
                    -- reversal, confirmed by that approver in this transaction too, lists the Refund.
                    OR EXISTS(SELECT 1 FROM app.settlement_corrections settlement_correction
                        JOIN app.financial_drafts draft ON draft.id=settlement_correction.correlation_id
                            AND draft.kind='SETTLEMENT_CORRECTION'
                            AND draft.payload->>'variant'='RETURN_REVERSAL_COMPANION'
                        JOIN app.financial_draft_decisions decision
                            ON decision.draft_id=draft.id AND decision.decision='CONFIRMED'
                            AND decision.decided_by=settlement_correction.actor_id
                        JOIN app.financial_draft_decisions reversal_decision
                            ON reversal_decision.draft_id::text=draft.payload->>'return_reversal_draft_id'
                            AND reversal_decision.decision='CONFIRMED'
                            AND reversal_decision.decided_by=settlement_correction.actor_id
                        JOIN app.settlement_correction_effects effect
                            ON effect.settlement_correction_id=settlement_correction.id
                            AND effect.refund_correction_id=(p_correction).id
                        WHERE settlement_correction.actor_id=(p_correction).actor_id
                          AND decision.result->>'transaction_id'=pg_current_xact_id()::text
                          AND decision.decided_at>=transaction_timestamp()
                          AND reversal_decision.result->>'transaction_id'=pg_current_xact_id()::text
                          AND reversal_decision.decided_at>=transaction_timestamp()
                          AND settlement_correction.final_settlement_id
                              =app.settlement_refund_owner(refund.id)
                          AND app.settlement_return_reversal_refund(
                              reversal_decision.draft_id,refund.id)))""",
        1,
    ),
)

RECOVERY_AMOUNT = "app.settlement_return_reversal_recovery_amount(app.refund_corrections)"
RECOVERY_AMOUNT_REPLACEMENTS = (
    (
        """
                AND draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='RETURN_REVERSAL'""",
        """
                -- Sub-slice 10e-3d-2d-2b-2: or the companion that links the charge-back of its
                -- Settlement's Refund (its draft's source lists that charge-back).
                AND draft.kind='SETTLEMENT_CORRECTION'
                AND draft.payload->>'variant' IN ('RETURN_REVERSAL','RETURN_REVERSAL_COMPANION')""",
        1,
    ),
)

PATCHES = (
    (FOLLOW, FOLLOW_REPLACEMENTS),
    (STATE, STATE_REPLACEMENTS),
    (COMPANION_SOURCE, COMPANION_SOURCE_REPLACEMENTS),
    (ASSERT, ASSERT_REPLACEMENTS),
    (CONFIRM, CONFIRM_REPLACEMENTS),
    (RESULT, RESULT_REPLACEMENTS),
    (REVERSAL_REFUND, REVERSAL_REFUND_REPLACEMENTS),
    (RECOVERY_ALLOWED, RECOVERY_ALLOWED_REPLACEMENTS),
    (RECOVERY_AMOUNT, RECOVERY_AMOUNT_REPLACEMENTS),
)


def _patch(signature: str, replacements: tuple[tuple[str, str, int], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after, count in replacements:
        if definition.count(before) != count:
            raise RuntimeError(f"Return reversal other Refund follow contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(FUNCTION_SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    op.execute(
        f"REVOKE ALL ON FUNCTION {REFUND_OWNER} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )


def downgrade() -> None:
    raise RuntimeError("Return reversal other Refund follow migration is forward-only")
