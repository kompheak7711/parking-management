# ruff: noqa: E501
"""Lease Deposit forfeiture reversal drafts (BR-AUTH-010, BR-DEP-019; V1-056 sub-slice 6b).

Owner answers to Q-2026-10-04-13 and Q-2026-10-04-14 (2026-10-04):
- The reversal of a confirmed Lease Deposit forfeiture is a draft: Staff holding
  deposits.correct record it with a reason and an evidence reference (Option A of
  Q-2026-10-04-13: "record under deposits.correct"), and only a financial.approve holder
  confirms it. The confirmation runs the existing reversal
  function (migration 28) as its owner with the approver as actor, so every earlier reversal
  rule applies. The one-call reversal stays closed (migration 83).
- Moved from slice 6 round 3: a new Lease forfeiture draft also refuses a disposition id that
  a Reservation Deposit draft will use (its outcome_id); draft reads are filtered by the
  capability the draft was prepared under, not only by kind.

Additive and relaxing: new functions; a DEPOSIT_FORFEITURE draft may also be prepared under
deposits.correct (the draft table's two capability checks and the decision table's withdrawal
check gain that value, so the preparer can withdraw it; owner answer to Q-2026-10-05-15). The forfeiture draft
record function gets one more refusal of a Reservation draft's outcome id (owner-directed,
Q-2026-10-04-14). The earlier draft read functions stay unchanged and granted; the application
uses the new capability-scoped reads.
"""

from alembic import op
from sqlalchemy import text

revision = "20261019_84"
down_revision = "20261018_83"
branch_labels = None
depends_on = None

FORFEITURE_DRAFT = "app.record_lease_deposit_forfeiture_draft(uuid,uuid,uuid,uuid,uuid,text,text)"
SOURCE = "app.lease_deposit_reversal_source(uuid,uuid)"
RECORD_DRAFT = "app.record_lease_deposit_reversal_draft(uuid,uuid,uuid,uuid,uuid,text,text,text)"
CONFIRM_DRAFT = "app.confirm_lease_deposit_reversal_draft(uuid,uuid,uuid,uuid,text)"
READ = (
    "app.financial_draft_resource_by_capability(uuid,uuid,uuid,text[])",
    "app.list_financial_drafts_by_capability(uuid,uuid,text[],text,integer,timestamp with time zone,uuid)",
)

PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        FORFEITURE_DRAFT,
        (
            (
                "                      AND draft.payload->>'disposition_id'=p_disposition::text)",
                "                      -- A Reservation draft's outcome_id becomes its disposition id.\n"
                "                      AND p_disposition::text IN (draft.payload->>'disposition_id',\n"
                "                          draft.payload->>'outcome_id'))",
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
            raise RuntimeError(f"Lease Deposit reversal source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def _single_check(pattern: str) -> str:
    names = (
        op.get_bind()
        .execute(
            text(
                "SELECT conname FROM pg_catalog.pg_constraint "
                "WHERE conrelid='app.financial_drafts'::regclass AND contype='c' "
                "AND pg_catalog.pg_get_constraintdef(oid) LIKE :pattern"
            ),
            {"pattern": pattern},
        )
        .scalars()
        .all()
    )
    if len(names) != 1:
        raise RuntimeError(f"Financial draft capability constraint is not unique: {pattern}")
    return str(names[0])


def upgrade() -> None:
    capability = _single_check("CHECK ((prepare_capability = ANY%")
    kind_capability = _single_check("%kind = 'DEPOSIT_FORFEITURE'%")
    # Relaxing: a DEPOSIT_FORFEITURE draft may also be prepared under deposits.correct.
    op.execute(f"""
        ALTER TABLE app.financial_drafts DROP CONSTRAINT {capability};
        ALTER TABLE app.financial_drafts ADD CONSTRAINT {capability} CHECK (prepare_capability IN (
            'refunds.create','deposits.dispose','reservation_deposits.dispose',
            'reservation_deposits.refund','payments.allocations.reverse',
            'final_settlements.prepare','deposits.correct'));
        ALTER TABLE app.financial_drafts DROP CONSTRAINT {kind_capability};
        ALTER TABLE app.financial_drafts ADD CONSTRAINT {kind_capability} CHECK (
            (kind = 'REFUND' AND prepare_capability IN ('refunds.create','reservation_deposits.refund'))
            OR (kind = 'DEPOSIT_FORFEITURE'
                AND prepare_capability IN ('deposits.dispose','reservation_deposits.dispose','deposits.correct'))
            OR (kind = 'PAYMENT_MOVE' AND prepare_capability = 'payments.allocations.reverse')
            OR (kind IN ('FINAL_SETTLEMENT','SETTLEMENT_CORRECTION')
                AND prepare_capability = 'final_settlements.prepare'));
    """)
    # Relaxing: the preparer of a deposits.correct draft withdraws it with that capability
    # (owner answer to Q-2026-10-05-15); CONFIRMED and REJECTED are unchanged.
    op.execute("""
        ALTER TABLE app.financial_draft_decisions DROP CONSTRAINT financial_draft_decision_shape;
        ALTER TABLE app.financial_draft_decisions ADD CONSTRAINT financial_draft_decision_shape CHECK (
            (decision = 'CONFIRMED' AND authorization_reference = 'financial.approve'
                AND result IS NOT NULL)
            OR (decision = 'REJECTED' AND authorization_reference = 'financial.approve'
                AND reason IS NOT NULL AND result IS NULL)
            OR (decision = 'WITHDRAWN' AND reason IS NOT NULL AND result IS NULL
                AND authorization_reference IN (
                    'refunds.create','deposits.dispose','reservation_deposits.dispose',
                    'reservation_deposits.refund','payments.allocations.reverse',
                    'final_settlements.prepare','deposits.correct'
                ))
        );
    """)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    op.execute("""
        -- Internal: the current reversal source of one Lease Deposit forfeiture, or a refusal.
        CREATE FUNCTION app.lease_deposit_reversal_source(p_property uuid,p_disposition uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_disposition app.deposit_dispositions%ROWTYPE;
        BEGIN
            SELECT * INTO v_disposition FROM app.deposit_dispositions WHERE id=p_disposition;
            IF NOT FOUND OR v_disposition.governing_lease_id IS NULL
                OR app.deposit_property_id(v_disposition.deposit_id) IS DISTINCT FROM p_property
            THEN RAISE EXCEPTION 'Lease Deposit forfeiture was not found' USING ERRCODE='P0002'; END IF;
            IF EXISTS (SELECT 1 FROM app.deposit_disposition_reversals reversal
                WHERE reversal.deposit_disposition_id=p_disposition)
            THEN RAISE EXCEPTION 'The forfeiture is already reversed' USING ERRCODE='22023'; END IF;
            RETURN jsonb_build_object('deposit_id',v_disposition.deposit_id,
                'lease_id',v_disposition.governing_lease_id,
                'amount_usd_cents',v_disposition.amount_usd_cents,
                'state_version',app.deposit_disposition_state_version(v_disposition.deposit_id));
        END $$;

        -- Staff record the reversal of one forfeiture as a draft (deposits.correct); it has no
        -- financial effect until a financial.approve holder confirms.
        CREATE FUNCTION app.record_lease_deposit_reversal_draft(p_property uuid,p_actor uuid,p_draft uuid,
            p_disposition uuid,p_reversal uuid,p_reason text,p_evidence text,p_authorization text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_input jsonb; v_source jsonb; v_existing app.financial_drafts%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property,p_actor);
            PERFORM app.assert_active_financial_actor(p_actor,p_property);
            IF p_authorization IS DISTINCT FROM 'deposits.correct'
            THEN RAISE EXCEPTION 'Lease Deposit forfeiture reversal draft authorization is invalid'
                USING ERRCODE='42501'; END IF;
            IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_disposition IS NULL
                OR p_reversal IS NULL OR p_reversal='00000000-0000-0000-0000-000000000000'
                OR p_reversal IN (p_draft,p_disposition)
                OR app.lease_notice_text_valid(p_reason,500) IS NOT TRUE
                OR app.lease_notice_text_valid(p_evidence,500) IS NOT TRUE
            THEN RAISE EXCEPTION 'Lease Deposit forfeiture reversal draft input is invalid'
                USING ERRCODE='22023'; END IF;
            v_input:=jsonb_build_object('variant','LEASE_FORFEITURE_REVERSAL','disposition_id',p_disposition,
                'reversal_id',p_reversal,'reason',p_reason,'evidence_reference',p_evidence);
            -- An exact repeat replays before any current-state check.
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
            SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
            IF FOUND THEN
                IF v_existing.property_id=p_property AND v_existing.kind='DEPOSIT_FORFEITURE'
                    AND v_existing.prepared_by=p_actor
                    AND jsonb_build_object('variant',v_existing.payload->'variant',
                        'disposition_id',v_existing.payload->'disposition_id',
                        'reversal_id',v_existing.payload->'reversal_id',
                        'reason',v_existing.payload->'reason',
                        'evidence_reference',v_existing.payload->'evidence_reference')=v_input
                THEN RETURN app.financial_draft_json(v_existing); END IF;
                RAISE EXCEPTION 'Lease Deposit forfeiture reversal draft identity was reused' USING ERRCODE='P5205';
            END IF;
            v_source:=app.lease_deposit_reversal_source(p_property,p_disposition);
            -- The same per-Deposit lock as the forfeiture drafts.
            PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || (v_source->>'deposit_id'),0));
            v_source:=app.lease_deposit_reversal_source(p_property,p_disposition);
            IF EXISTS (SELECT 1 FROM app.financial_drafts draft
                WHERE draft.property_id=p_property AND draft.kind='DEPOSIT_FORFEITURE'
                  AND draft.payload->>'variant'='LEASE_FORFEITURE_REVERSAL'
                  AND draft.payload->>'disposition_id'=p_disposition::text
                  AND NOT EXISTS (SELECT 1 FROM app.financial_draft_decisions decision WHERE decision.draft_id=draft.id))
            THEN RAISE EXCEPTION 'A reversal draft for this forfeiture is already waiting' USING ERRCODE='55000'; END IF;
            -- A reversal id is used once: not by a recorded reversal, an audit event (the reversal
            -- audit takes its id) or any draft's reversal, correction, disposition or outcome id.
            IF EXISTS (SELECT 1 FROM app.deposit_disposition_reversals WHERE id=p_reversal)
                OR EXISTS (SELECT 1 FROM app.audit_events WHERE id=p_reversal)
                OR EXISTS (SELECT 1 FROM app.financial_drafts draft
                    WHERE p_reversal::text IN (draft.payload->>'reversal_id',draft.payload->>'correction_id',
                        draft.payload->>'disposition_id',draft.payload->>'outcome_id'))
            THEN RAISE EXCEPTION 'Deposit disposition reversal identity was reused' USING ERRCODE='P5205'; END IF;
            RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'DEPOSIT_FORFEITURE','deposits.correct',
                v_input || v_source,'deposit-state:' || (v_source->>'state_version'),p_reason);
        END $$;

        -- A financial.approve holder confirms: the existing reversal function runs with the
        -- approver as actor, so every earlier reversal rule applies.
        CREATE FUNCTION app.confirm_lease_deposit_reversal_draft(p_property uuid,p_actor uuid,p_disposition uuid,
            p_draft uuid,p_authorization text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE; v_source jsonb; v_snapshot jsonb; v_digest text;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property,p_actor);
            PERFORM app.assert_active_financial_actor(p_actor,p_property);
            IF p_authorization IS DISTINCT FROM 'financial.approve' THEN
                RAISE EXCEPTION 'Only financial.approve may confirm a forfeiture reversal draft' USING ERRCODE='42501'; END IF;
            IF p_draft IS NULL OR p_disposition IS NULL THEN
                RAISE EXCEPTION 'Lease Deposit forfeiture reversal confirmation is invalid' USING ERRCODE='22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
            SELECT draft.* INTO v_draft FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
            WHERE draft.id=p_draft AND draft.property_id=p_property AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor AND draft.payload->>'variant'='LEASE_FORFEITURE_REVERSAL'
              AND draft.payload->>'disposition_id'=p_disposition::text;
            IF FOUND THEN
                -- An exact replay returns the stored result of the first confirmation.
                SELECT command.result_snapshot INTO STRICT v_snapshot FROM app.deposit_commands command
                WHERE command.actor_id=p_actor AND command.property_id=p_property
                  AND command.action='deposit.disposition.reverse' AND command.idempotency_key=p_draft;
                RETURN jsonb_build_object('draft',app.financial_draft_json(v_draft),'deposit',v_snapshot);
            END IF;
            v_draft:=app.lock_pending_financial_draft(p_property,p_draft);
            IF v_draft.kind<>'DEPOSIT_FORFEITURE' OR v_draft.prepare_capability<>'deposits.correct'
                OR v_draft.payload->>'variant' IS DISTINCT FROM 'LEASE_FORFEITURE_REVERSAL'
                OR v_draft.payload->>'disposition_id' IS DISTINCT FROM p_disposition::text
            THEN RAISE EXCEPTION 'Financial draft was not found' USING ERRCODE='P0002'; END IF;
            IF EXISTS (SELECT 1 FROM app.deposit_commands command
                WHERE command.actor_id=p_actor AND command.property_id=p_property
                  AND command.action='deposit.disposition.reverse' AND command.idempotency_key=p_draft)
            THEN RAISE EXCEPTION 'Lease Deposit forfeiture reversal draft identity was reused' USING ERRCODE='P5205'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || (v_draft.payload->>'deposit_id'),0));
            -- Lock the Deposit row before the stale check, so no other Deposit change can commit
            -- between the check and the reversal (the reversal locks the same row later).
            PERFORM 1 FROM app.deposits WHERE id=(v_draft.payload->>'deposit_id')::uuid FOR UPDATE;
            v_source:=app.lease_deposit_reversal_source(p_property,p_disposition);
            -- A draft is stale when the Deposit changed since it was recorded.
            IF (v_source->>'state_version') IS DISTINCT FROM (v_draft.payload->>'state_version')
                OR (v_source->>'deposit_id') IS DISTINCT FROM (v_draft.payload->>'deposit_id')
            THEN RAISE EXCEPTION 'Lease Deposit forfeiture reversal draft is stale' USING ERRCODE='23514'; END IF;
            v_digest:=encode(sha256(convert_to('lease-deposit-forfeiture-reversal-draft:' || p_draft::text,'UTF8')),'hex');
            PERFORM app.reverse_deposit_disposition_v2(p_property,p_actor,p_draft,v_digest,
                (v_draft.payload->>'reversal_id')::uuid,p_disposition,v_draft.payload->>'reason',
                v_draft.payload->>'evidence_reference','deposits.correct');
            SELECT command.result_snapshot INTO STRICT v_snapshot FROM app.deposit_commands command
            WHERE command.actor_id=p_actor AND command.property_id=p_property
              AND command.action='deposit.disposition.reverse' AND command.idempotency_key=p_draft;
            PERFORM app.confirm_financial_draft_record(p_property,p_actor,p_draft,'DEPOSIT_FORFEITURE',
                jsonb_build_object('deposit_id',v_draft.payload->>'deposit_id','disposition_id',p_disposition,
                    'reversal_id',v_draft.payload->>'reversal_id'),'financial.approve');
            RETURN jsonb_build_object('draft',app.financial_draft_json(v_draft),'deposit',v_snapshot);
        END $$;

        -- Draft reads by the capability each draft was prepared under (moved from slice 6
        -- round 3): a reader without financial.approve passes only the capabilities it holds.
        CREATE FUNCTION app.financial_draft_resource_by_capability(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid, p_capabilities text[]
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE;
        BEGIN
            PERFORM 1 FROM app.user_accounts
            WHERE actor_id = p_actor_id AND lifecycle_state = 'active';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Financial draft read requires an active human actor'
                    USING ERRCODE = '42501';
            END IF;
            IF p_capabilities IS NULL OR cardinality(p_capabilities) NOT BETWEEN 1 AND 7
                OR array_position(p_capabilities, NULL) IS NOT NULL
            THEN RAISE EXCEPTION 'Financial draft capabilities are invalid' USING ERRCODE = '22023'; END IF;
            SELECT * INTO v_draft FROM app.financial_drafts
            WHERE id = p_draft_id AND property_id = p_property_id
              AND prepare_capability = ANY(p_capabilities);
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Financial draft was not found' USING ERRCODE = 'P0002';
            END IF;
            RETURN app.financial_draft_json(v_draft);
        END $$;

        CREATE FUNCTION app.list_financial_drafts_by_capability(
            p_property_id uuid, p_actor_id uuid, p_capabilities text[], p_state text, p_limit integer,
            p_after_prepared_at timestamptz, p_after_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_items jsonb;
        BEGIN
            PERFORM 1 FROM app.user_accounts
            WHERE actor_id = p_actor_id AND lifecycle_state = 'active';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Financial draft read requires an active human actor'
                    USING ERRCODE = '42501';
            END IF;
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100
                OR p_capabilities IS NULL OR cardinality(p_capabilities) NOT BETWEEN 1 AND 7
                OR array_position(p_capabilities, NULL) IS NOT NULL
                OR (p_state IS NOT NULL
                    AND p_state NOT IN ('PENDING','CONFIRMED','REJECTED','WITHDRAWN'))
                OR (p_after_prepared_at IS NULL) <> (p_after_id IS NULL)
            THEN RAISE EXCEPTION 'Financial draft page is invalid' USING ERRCODE = '22023'; END IF;
            SELECT COALESCE(jsonb_agg(app.financial_draft_json(page.draft)
                ORDER BY (page.draft).prepared_at DESC, (page.draft).id DESC), '[]'::jsonb)
            INTO v_items
            FROM (
                SELECT draft FROM app.financial_drafts AS draft
                LEFT JOIN app.financial_draft_decisions AS decision ON decision.draft_id = draft.id
                WHERE draft.property_id = p_property_id
                  AND draft.prepare_capability = ANY(p_capabilities)
                  AND (p_state IS NULL OR COALESCE(decision.decision, 'PENDING') = p_state)
                  AND (p_after_id IS NULL OR (draft.prepared_at, draft.id) < (p_after_prepared_at, p_after_id))
                ORDER BY draft.prepared_at DESC, draft.id DESC
                LIMIT p_limit
            ) AS page;
            RETURN jsonb_build_object('items', v_items);
        END $$;
    """)
    for function in (SOURCE, RECORD_DRAFT, CONFIRM_DRAFT, *READ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD_DRAFT}, {CONFIRM_DRAFT} TO prm_financial")
    for function in READ:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("Lease Deposit reversal draft migration is forward-only")
