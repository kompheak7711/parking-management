# ruff: noqa: E501
"""Financial drafts: prepare first, confirm only under financial.approve (BR-AUTH-010, DL-069).

Additive. Two append-only tables hold a draft and its single decision (CONFIRMED, REJECTED or
WITHDRAWN). A draft has no financial effect. Draft kinds get their own record and confirm
functions in later V1-056 migrations; those functions use the internal helpers added here,
which the runtime and financial roles cannot call directly. The application checks the
capabilities; the database checks the active human actor, the Property and the recorded
authorization reference, as in the existing financial command functions.
"""

from alembic import op

revision = "20261012_77"
down_revision = "20261011_76"
branch_labels = None
depends_on = None

INTERNAL = (
    "app.insert_financial_draft(uuid,uuid,uuid,text,text,jsonb,text,text)",
    "app.confirm_financial_draft_record(uuid,uuid,uuid,text,jsonb,text)",
    "app.reject_financial_draft_mutation()",
)
FINANCIAL = (
    "app.reject_financial_draft(uuid,uuid,uuid,text,text)",
    "app.withdraw_financial_draft(uuid,uuid,uuid,text,text)",
)
READ = (
    "app.financial_draft_resource(uuid,uuid,uuid,text[])",
    "app.list_financial_drafts(uuid,uuid,text[],text,integer,timestamp with time zone,uuid)",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.financial_drafts (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            kind text NOT NULL CHECK (kind IN (
                'REFUND','DEPOSIT_FORFEITURE','PAYMENT_MOVE','FINAL_SETTLEMENT','SETTLEMENT_CORRECTION'
            )),
            prepare_capability text NOT NULL CHECK (prepare_capability IN (
                'refunds.create','deposits.dispose','reservation_deposits.dispose',
                'reservation_deposits.refund','payments.allocations.reverse',
                'final_settlements.prepare'
            )),
            payload jsonb NOT NULL
                CHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 16000),
            source_revision text
                CHECK (source_revision IS NULL OR length(source_revision) BETWEEN 1 AND 500),
            reason text NOT NULL
                CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 1000),
            prepared_at timestamptz NOT NULL,
            prepared_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            CONSTRAINT financial_draft_kind_capability CHECK (
                (kind = 'REFUND' AND prepare_capability IN ('refunds.create','reservation_deposits.refund'))
                OR (kind = 'DEPOSIT_FORFEITURE'
                    AND prepare_capability IN ('deposits.dispose','reservation_deposits.dispose'))
                OR (kind = 'PAYMENT_MOVE' AND prepare_capability = 'payments.allocations.reverse')
                OR (kind IN ('FINAL_SETTLEMENT','SETTLEMENT_CORRECTION')
                    AND prepare_capability = 'final_settlements.prepare')
            )
        );
        CREATE INDEX financial_drafts_property_history_idx
            ON app.financial_drafts(property_id, prepared_at DESC, id DESC);

        CREATE TABLE app.financial_draft_decisions (
            draft_id uuid PRIMARY KEY REFERENCES app.financial_drafts(id) ON DELETE RESTRICT,
            decision text NOT NULL CHECK (decision IN ('CONFIRMED','REJECTED','WITHDRAWN')),
            reason text CHECK (reason IS NULL OR (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 1000)),
            decided_at timestamptz NOT NULL,
            decided_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL,
            result jsonb CHECK (result IS NULL OR (jsonb_typeof(result) = 'object'
                AND octet_length(result::text) <= 16000)),
            CONSTRAINT financial_draft_decision_shape CHECK (
                (decision = 'CONFIRMED' AND authorization_reference = 'financial.approve'
                    AND result IS NOT NULL)
                OR (decision = 'REJECTED' AND authorization_reference = 'financial.approve'
                    AND reason IS NOT NULL AND result IS NULL)
                OR (decision = 'WITHDRAWN' AND reason IS NOT NULL AND result IS NULL
                    AND authorization_reference IN (
                        'refunds.create','deposits.dispose','reservation_deposits.dispose',
                        'reservation_deposits.refund','payments.allocations.reverse',
                        'final_settlements.prepare'
                    ))
            )
        );

        CREATE FUNCTION app.reject_financial_draft_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Financial draft history is append-only' USING ERRCODE = '55000';
        END $$;
        CREATE TRIGGER financial_drafts_immutable BEFORE UPDATE OR DELETE
            ON app.financial_drafts FOR EACH ROW
            EXECUTE FUNCTION app.reject_financial_draft_mutation();
        CREATE TRIGGER financial_drafts_no_truncate BEFORE TRUNCATE
            ON app.financial_drafts FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_financial_draft_mutation();
        CREATE TRIGGER financial_draft_decisions_immutable BEFORE UPDATE OR DELETE
            ON app.financial_draft_decisions FOR EACH ROW
            EXECUTE FUNCTION app.reject_financial_draft_mutation();
        CREATE TRIGGER financial_draft_decisions_no_truncate BEFORE TRUNCATE
            ON app.financial_draft_decisions FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_financial_draft_mutation();

        CREATE FUNCTION app.financial_draft_json(p_draft app.financial_drafts)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT jsonb_build_object(
                'draft_id', p_draft.id,
                'property_id', p_draft.property_id,
                'kind', p_draft.kind,
                'prepare_capability', p_draft.prepare_capability,
                'payload', p_draft.payload,
                'source_revision', p_draft.source_revision,
                'reason', p_draft.reason,
                'prepared_at', p_draft.prepared_at,
                'prepared_by', p_draft.prepared_by,
                'state', COALESCE(decision.decision, 'PENDING'),
                'decision', CASE WHEN decision.draft_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'decision', decision.decision,
                    'reason', decision.reason,
                    'decided_at', decision.decided_at,
                    'decided_by', decision.decided_by,
                    'authorization_reference', decision.authorization_reference,
                    'result', decision.result
                ) END
            )
            FROM (SELECT 1) AS anchor
            LEFT JOIN app.financial_draft_decisions AS decision ON decision.draft_id = p_draft.id
        $$;

        CREATE FUNCTION app.insert_financial_draft(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid, p_kind text,
            p_prepare_capability text, p_payload jsonb, p_source_revision text, p_reason text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            IF p_draft_id IS NULL OR p_kind IS NULL OR p_prepare_capability IS NULL
                OR p_payload IS NULL OR p_reason IS NULL
            THEN RAISE EXCEPTION 'Financial draft input is invalid' USING ERRCODE = '22023'; END IF;
            INSERT INTO app.financial_drafts(
                id, property_id, kind, prepare_capability, payload, source_revision, reason,
                prepared_at, prepared_by
            ) VALUES (
                p_draft_id, p_property_id, p_kind, p_prepare_capability, p_payload,
                p_source_revision, p_reason, clock_timestamp(), p_actor_id
            ) RETURNING * INTO v_draft;
            RETURN app.financial_draft_json(v_draft);
        END $$;

        CREATE FUNCTION app.lock_pending_financial_draft(
            p_property_id uuid, p_draft_id uuid
        ) RETURNS app.financial_drafts LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE;
        BEGIN
            SELECT * INTO v_draft FROM app.financial_drafts
            WHERE id = p_draft_id AND property_id = p_property_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Financial draft was not found' USING ERRCODE = 'P0002';
            END IF;
            IF EXISTS (SELECT 1 FROM app.financial_draft_decisions WHERE draft_id = p_draft_id) THEN
                RAISE EXCEPTION 'Financial draft is already decided' USING ERRCODE = '55000';
            END IF;
            RETURN v_draft;
        END $$;

        CREATE FUNCTION app.confirm_financial_draft_record(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid, p_kind text, p_result jsonb,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            IF p_authorization_reference IS DISTINCT FROM 'financial.approve' THEN
                RAISE EXCEPTION 'Only financial.approve may confirm a draft' USING ERRCODE = '42501';
            END IF;
            v_draft := app.lock_pending_financial_draft(p_property_id, p_draft_id);
            IF p_kind IS NULL OR v_draft.kind <> p_kind THEN
                RAISE EXCEPTION 'Financial draft kind does not match the confirm command'
                    USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.financial_draft_decisions(
                draft_id, decision, reason, decided_at, decided_by, authorization_reference, result
            ) VALUES (
                v_draft.id, 'CONFIRMED', NULL, clock_timestamp(), p_actor_id, 'financial.approve',
                p_result
            );
            RETURN app.financial_draft_json(v_draft);
        END $$;

        CREATE FUNCTION app.decided_financial_draft_replay(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid, p_decision text, p_reason text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE;
        BEGIN
            SELECT draft.* INTO v_draft FROM app.financial_drafts AS draft
            JOIN app.financial_draft_decisions AS decision ON decision.draft_id = draft.id
            WHERE draft.id = p_draft_id AND draft.property_id = p_property_id
              AND decision.decision = p_decision AND decision.decided_by = p_actor_id
              AND decision.reason IS NOT DISTINCT FROM p_reason;
            IF NOT FOUND THEN RETURN NULL; END IF;
            RETURN app.financial_draft_json(v_draft);
        END $$;

        CREATE FUNCTION app.reject_financial_draft(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid, p_reason text,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE; v_replay jsonb;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            IF p_authorization_reference IS DISTINCT FROM 'financial.approve' THEN
                RAISE EXCEPTION 'Only financial.approve may reject a draft' USING ERRCODE = '42501';
            END IF;
            IF p_reason IS NULL OR p_reason <> btrim(p_reason)
                OR length(p_reason) NOT BETWEEN 1 AND 1000
            THEN RAISE EXCEPTION 'Rejection reason is invalid' USING ERRCODE = '22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft_id::text, 0));
            v_replay := app.decided_financial_draft_replay(
                p_property_id, p_actor_id, p_draft_id, 'REJECTED', p_reason
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            v_draft := app.lock_pending_financial_draft(p_property_id, p_draft_id);
            INSERT INTO app.financial_draft_decisions(
                draft_id, decision, reason, decided_at, decided_by, authorization_reference, result
            ) VALUES (
                v_draft.id, 'REJECTED', p_reason, clock_timestamp(), p_actor_id,
                'financial.approve', NULL
            );
            RETURN app.financial_draft_json(v_draft);
        END $$;

        CREATE FUNCTION app.withdraw_financial_draft(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid, p_reason text,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE; v_replay jsonb;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id, p_actor_id);
            IF p_reason IS NULL OR p_reason <> btrim(p_reason)
                OR length(p_reason) NOT BETWEEN 1 AND 1000
            THEN RAISE EXCEPTION 'Withdrawal reason is invalid' USING ERRCODE = '22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft_id::text, 0));
            SELECT * INTO v_draft FROM app.financial_drafts
            WHERE id = p_draft_id AND property_id = p_property_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Financial draft was not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_draft.prepared_by <> p_actor_id
                OR p_authorization_reference IS DISTINCT FROM v_draft.prepare_capability
            THEN
                RAISE EXCEPTION 'Only the preparer may withdraw a draft' USING ERRCODE = '42501';
            END IF;
            v_replay := app.decided_financial_draft_replay(
                p_property_id, p_actor_id, p_draft_id, 'WITHDRAWN', p_reason
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            v_draft := app.lock_pending_financial_draft(p_property_id, p_draft_id);
            INSERT INTO app.financial_draft_decisions(
                draft_id, decision, reason, decided_at, decided_by, authorization_reference, result
            ) VALUES (
                v_draft.id, 'WITHDRAWN', p_reason, clock_timestamp(), p_actor_id,
                v_draft.prepare_capability, NULL
            );
            RETURN app.financial_draft_json(v_draft);
        END $$;

        CREATE FUNCTION app.financial_draft_resource(
            p_property_id uuid, p_actor_id uuid, p_draft_id uuid, p_kinds text[]
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE;
        BEGIN
            PERFORM 1 FROM app.user_accounts
            WHERE actor_id = p_actor_id AND lifecycle_state = 'active';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Financial draft read requires an active human actor'
                    USING ERRCODE = '42501';
            END IF;
            IF p_kinds IS NULL OR cardinality(p_kinds) NOT BETWEEN 1 AND 5 THEN
                RAISE EXCEPTION 'Financial draft kinds are invalid' USING ERRCODE = '22023';
            END IF;
            SELECT * INTO v_draft FROM app.financial_drafts
            WHERE id = p_draft_id AND property_id = p_property_id AND kind = ANY(p_kinds);
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Financial draft was not found' USING ERRCODE = 'P0002';
            END IF;
            RETURN app.financial_draft_json(v_draft);
        END $$;

        CREATE FUNCTION app.list_financial_drafts(
            p_property_id uuid, p_actor_id uuid, p_kinds text[], p_state text, p_limit integer,
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
                OR p_kinds IS NULL OR cardinality(p_kinds) NOT BETWEEN 1 AND 5
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
                WHERE draft.property_id = p_property_id AND draft.kind = ANY(p_kinds)
                  AND (p_state IS NULL OR COALESCE(decision.decision, 'PENDING') = p_state)
                  AND (p_after_id IS NULL OR (draft.prepared_at, draft.id) < (p_after_prepared_at, p_after_id))
                ORDER BY draft.prepared_at DESC, draft.id DESC
                LIMIT p_limit
            ) AS page;
            RETURN jsonb_build_object('items', v_items);
        END $$;

        REVOKE ALL ON TABLE app.financial_drafts, app.financial_draft_decisions
            FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap;
        """
    )
    for function in (
        *INTERNAL,
        *FINANCIAL,
        *READ,
        "app.financial_draft_json(app.financial_drafts)",
        "app.lock_pending_financial_draft(uuid,uuid)",
        "app.decided_financial_draft_replay(uuid,uuid,uuid,text,text)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    for function in FINANCIAL:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")
    for function in READ:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("Financial drafts are forward-only")
