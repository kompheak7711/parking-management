"""V1-058 R3 Move-out M5: read the Final Settlements of a Property without starting one.

The Move-out screens (DESIGN.md "Move-out (round 3)") show for each Lease whether its Final
Settlement is open, waits for a Manager ("To confirm") or is closed. Until now the only way to
learn a Lease's Settlement was `app.start_final_settlement`, which opens one when none exists, so
a screen could not look without writing.

`app.final_settlements_read(property, actor, lease)` returns `{items[]}`: each Settlement of the
Property (or only the given Lease's) as `app.final_settlement_json` gives it, plus
`pending_draft`, true while a FINAL_SETTLEMENT draft for it waits for a decision. Newest first.
The draft's identity is not shown here; the shared draft reads show it to those allowed. The
application checks `final_settlements.prepare` or `financial.approve` first, as for the preview.

Additive only: one new function; no existing table, function or grant changes.
"""

from alembic import op

revision = "20270315_234"
down_revision = "20270314_233"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION app.final_settlements_read(p_property uuid, p_actor uuid, p_lease uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL
            THEN RAISE EXCEPTION 'Final Settlement read input is invalid'
                USING ERRCODE='22023'; END IF;
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts account
                    JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
                    WHERE account.actor_id=p_actor AND account.lifecycle_state='active'
                      AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Final Settlement read needs an active person'
                USING ERRCODE='42501'; END IF;
            IF NOT EXISTS(SELECT 1 FROM app.properties property WHERE property.id=p_property)
            THEN RAISE EXCEPTION 'Property was not found' USING ERRCODE='P0002'; END IF;
            IF p_lease IS NOT NULL AND NOT EXISTS(SELECT 1 FROM app.leases lease
                    JOIN app.units unit ON unit.id=lease.unit_id
                    WHERE lease.id=p_lease AND unit.property_id=p_property)
            THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE='P0002'; END IF;
            RETURN jsonb_build_object('items', (SELECT COALESCE(jsonb_agg(
                    app.final_settlement_json(settlement.id) || jsonb_build_object('pending_draft',
                        EXISTS(SELECT 1 FROM app.financial_drafts draft
                            WHERE draft.property_id=p_property AND draft.kind='FINAL_SETTLEMENT'
                              AND draft.payload->>'final_settlement_id'=settlement.id::text
                              AND NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                                  WHERE decision.draft_id=draft.id)))
                    ORDER BY settlement.started_at DESC, settlement.id), '[]'::jsonb)
                FROM app.final_settlements settlement
                WHERE settlement.property_id=p_property
                  AND (p_lease IS NULL OR settlement.lease_id=p_lease)));
        END $$;

        COMMENT ON FUNCTION app.final_settlements_read(uuid,uuid,uuid) IS
            'V1-058 R3 Move-out M5: the Final Settlements of a Property (or of one Lease), each '
            'with whether a draft waits; read only, starts nothing.';
        REVOKE ALL ON FUNCTION app.final_settlements_read(uuid,uuid,uuid)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.final_settlements_read(uuid,uuid,uuid) TO prm_runtime;
        """
    )


def downgrade() -> None:
    raise RuntimeError("The Final Settlement list read is forward-only; downgrade is not supported")
