# ruff: noqa: E501
"""Require original approved source and a current financial observation for disposition."""

from alembic import op
from sqlalchemy import text

revision = "20260914_58"
down_revision = "20260914_57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.lease_deposit_disposition_contexts (
            disposition_id uuid PRIMARY KEY CHECK(disposition_id<>'00000000-0000-0000-0000-000000000000'),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            action text NOT NULL DEFAULT 'deposit.disposition.record' CHECK(action='deposit.disposition.record'),
            request_digest text NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
            deposit_id uuid NOT NULL REFERENCES app.deposits(id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            amount_usd_cents bigint NOT NULL CHECK(amount_usd_cents>0),
            effective_date date NOT NULL CHECK(isfinite(effective_date)),
            reason text NOT NULL CHECK(app.lease_notice_text_valid(reason,1000)),
            authorization_reference text NOT NULL CHECK(authorization_reference='deposits.dispose'),
            termination_event_id uuid NOT NULL REFERENCES app.lease_commands(event_id) ON DELETE RESTRICT,
            governing_rule text NOT NULL CHECK(governing_rule IN ('BR-DEP-022','BR-DEP-023')),
            expected_state_version bigint NOT NULL CHECK(expected_state_version>0),
            recorded_at timestamptz NOT NULL DEFAULT statement_timestamp() CHECK(isfinite(recorded_at)),
            UNIQUE(property_id,actor_id,idempotency_key),
            CONSTRAINT disposition_context_source_fk FOREIGN KEY(disposition_id)
                REFERENCES app.deposit_dispositions(id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT disposition_context_command_fk FOREIGN KEY(actor_id,property_id,action,idempotency_key)
                REFERENCES app.deposit_commands(actor_id,property_id,action,idempotency_key)
                ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
        );
        CREATE INDEX lease_deposit_disposition_contexts_source_idx
            ON app.lease_deposit_disposition_contexts(termination_event_id,deposit_id,disposition_id);

        CREATE FUNCTION app.require_lease_deposit_disposition_context(
            p_property uuid,p_actor uuid,p_key uuid,p_digest text,p_disposition uuid,
            p_deposit uuid,p_lease uuid,p_amount bigint,p_effective date,p_reason text,p_authorization text)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_context app.lease_deposit_disposition_contexts%ROWTYPE;
        DECLARE v_lease app.leases%ROWTYPE; v_deposit app.deposits%ROWTYPE;
        DECLARE v_event app.lease_commands%ROWTYPE; v_termination app.lease_termination_contexts%ROWTYPE;
        DECLARE v_warning_count integer;
        BEGIN
            SELECT * INTO v_context FROM app.lease_deposit_disposition_contexts WHERE disposition_id=p_disposition;
            IF NOT FOUND THEN RAISE EXCEPTION 'Approved Deposit disposition context is required' USING ERRCODE='22023'; END IF;
            IF ROW(v_context.property_id,v_context.actor_id,v_context.idempotency_key,v_context.request_digest,
                v_context.deposit_id,v_context.lease_id,v_context.amount_usd_cents,v_context.effective_date,
                v_context.reason,v_context.authorization_reference)
                IS DISTINCT FROM ROW(p_property,p_actor,p_key,p_digest,p_deposit,p_lease,p_amount,p_effective,p_reason,p_authorization)
            THEN RAISE EXCEPTION 'Deposit disposition context does not match the exact command' USING ERRCODE='22023'; END IF;
            -- Shared source locks precede the Deposit root and its MVCC guard.
            SELECT lease.* INTO v_lease FROM app.leases lease JOIN app.units unit ON unit.id=lease.unit_id
                WHERE lease.id=p_lease AND unit.property_id=p_property FOR SHARE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Deposit Lease source was not found' USING ERRCODE='P0002'; END IF;
            SELECT * INTO v_deposit FROM app.deposits WHERE id=p_deposit FOR UPDATE;
            IF NOT FOUND OR app.deposit_property_id(p_deposit) IS DISTINCT FROM p_property
            THEN RAISE EXCEPTION 'Deposit was not found' USING ERRCODE='P0002'; END IF;
            PERFORM app.serialize_deposit_state(p_deposit);
            SELECT * INTO v_event FROM app.lease_commands WHERE event_id=v_context.termination_event_id;
            IF v_lease.status IS DISTINCT FROM 'TERMINATED' OR v_deposit.lease_id IS DISTINCT FROM p_lease
                OR v_deposit.customer_id IS DISTINCT FROM v_lease.primary_tenant_id
                OR p_effective IS DISTINCT FROM v_lease.actual_termination_date
                OR v_event.event_id IS NULL OR v_event.action IS DISTINCT FROM 'lease.terminate'
                OR v_event.property_id IS DISTINCT FROM p_property OR v_event.lease_id IS DISTINCT FROM p_lease
                OR v_event.occurred_at IS DISTINCT FROM v_lease.terminated_at
                OR v_event.reason IS DISTINCT FROM v_lease.termination_reason
                OR v_event.result_snapshot->>'lease_id' IS DISTINCT FROM p_lease::text
                OR v_event.result_snapshot->>'property_id' IS DISTINCT FROM p_property::text
                OR v_event.result_snapshot->>'status' IS DISTINCT FROM 'TERMINATED'
                OR v_event.result_snapshot->>'actual_termination_date' IS DISTINCT FROM p_effective::text
            THEN RAISE EXCEPTION 'Approved Deposit termination source is invalid' USING ERRCODE='22023'; END IF;
            SELECT * INTO v_termination FROM app.lease_termination_contexts WHERE command_event_id=v_event.event_id;
            IF FOUND THEN
                IF ROW(v_termination.property_id,v_termination.actor_id,v_termination.idempotency_key,
                    v_termination.request_digest,v_termination.lease_id,v_termination.actual_termination_date,
                    v_termination.occurred_at,v_termination.governing_event_reference,v_termination.reason)
                    IS DISTINCT FROM ROW(v_event.property_id,v_event.actor_id,v_event.idempotency_key,
                    v_event.request_digest,v_event.lease_id,p_effective,v_event.occurred_at,
                    v_event.governing_event_reference,v_event.reason)
                    OR app.lease_termination_context_shape_valid(v_termination.context_data) IS NOT TRUE
                THEN RAISE EXCEPTION 'Signed termination authority does not match the original source' USING ERRCODE='22023'; END IF;
            END IF;
            IF v_context.governing_rule='BR-DEP-023' THEN
                IF v_deposit.deposit_type IS DISTINCT FROM 'SECURITY'
                    OR v_event.governing_event_reference IS DISTINCT FROM 'BR-LEASE-021'
                    OR p_effective>=v_lease.end_date
                    OR (v_termination.command_event_id IS NOT NULL
                        AND v_termination.context_data->>'basis' IS DISTINCT FROM 'VOLUNTARY_EARLY')
                THEN RAISE EXCEPTION 'Voluntary Security disposition source is invalid' USING ERRCODE='22023'; END IF;
            ELSIF v_context.governing_rule='BR-DEP-022' THEN
                IF v_event.governing_event_reference IS DISTINCT FROM 'BR-DEP-022'
                    OR v_termination.command_event_id IS NULL
                    OR v_termination.context_data->>'basis' IS DISTINCT FROM 'CUSTOMER_VIOLATION'
                THEN RAISE EXCEPTION 'Explicit approved pet-noncompliance termination is required' USING ERRCODE='22023'; END IF;
                SELECT count(*) INTO v_warning_count FROM app.lease_termination_warning_sources WHERE command_event_id=v_event.event_id;
                IF v_warning_count<3 OR v_warning_count<>jsonb_array_length(v_termination.context_data->'warning_ids')
                    OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(v_termination.context_data->'warning_ids') item
                        WHERE NOT EXISTS(SELECT 1 FROM app.lease_termination_warning_sources source
                            WHERE source.command_event_id=v_event.event_id AND source.warning_id=item::uuid))
                    OR EXISTS(SELECT 1 FROM app.lease_termination_warning_sources source
                        JOIN app.lease_violation_warnings warning ON warning.id=source.warning_id
                        WHERE source.command_event_id=v_event.event_id AND (warning.lease_id<>p_lease
                            OR NOT isfinite(warning.warning_date) OR NOT isfinite(warning.violation_date)
                            OR NOT isfinite(warning.occurred_at) OR warning.occurred_at>v_event.occurred_at
                            OR warning.warning_date>p_effective OR warning.violation_date>warning.warning_date
                            OR NOT app.lease_notice_text_valid(warning.lease_provision,2000)
                            OR NOT app.lease_notice_text_valid(warning.violation_description,2000)
                            OR NOT app.lease_notice_text_valid(warning.communication_record,2000)))
                THEN RAISE EXCEPTION 'Original general warning sources are invalid' USING ERRCODE='22023'; END IF;
            ELSE RAISE EXCEPTION 'Unsupported Deposit disposition rule' USING ERRCODE='22023';
            END IF;
            IF app.deposit_disposition_state_version(p_deposit) IS DISTINCT FROM v_context.expected_state_version
            THEN RAISE EXCEPTION 'Deposit financial observation changed' USING ERRCODE='P5801'; END IF;
        END $$;

        CREATE FUNCTION app.record_lease_deposit_disposition_with_context(
            p_property uuid,p_actor uuid,p_key uuid,p_digest text,p_disposition uuid,
            p_deposit uuid,p_lease uuid,p_amount bigint,p_effective date,p_reason text,p_authorization text,
            p_termination_event uuid,p_rule text,p_expected_state_version bigint)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_result jsonb; v_saved app.lease_deposit_disposition_contexts%ROWTYPE;
        BEGIN
            IF p_property IS NULL OR p_actor IS NULL OR p_key IS NULL
                OR p_key='00000000-0000-0000-0000-000000000000'
                OR p_digest IS NULL OR p_digest!~'^[0-9a-f]{64}$'
                OR p_authorization IS DISTINCT FROM 'deposits.dispose'
            THEN RAISE EXCEPTION 'Deposit command identity or authorization is invalid' USING ERRCODE='22023'; END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                p_property::text || ':' || p_actor::text || '-deposit.disposition.record-' || p_key::text,0));
            PERFORM 1 FROM app.user_accounts account JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
                WHERE account.actor_id=p_actor AND account.lifecycle_state='active' AND identity.identity_kind='HUMAN' FOR SHARE OF account;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease Deposit disposition actor is not active' USING ERRCODE='42501'; END IF;
            v_result:=app.replay_deposit_command(p_property,p_actor,'deposit.disposition.record',p_key,p_digest);
            IF v_result IS NOT NULL THEN
                SELECT * INTO v_saved FROM app.lease_deposit_disposition_contexts
                    WHERE property_id=p_property AND actor_id=p_actor AND idempotency_key=p_key;
                IF NOT FOUND OR ROW(v_saved.disposition_id,v_saved.deposit_id,v_saved.lease_id,
                    v_saved.amount_usd_cents,v_saved.effective_date,v_saved.reason,v_saved.authorization_reference,
                    v_saved.termination_event_id,v_saved.governing_rule,v_saved.expected_state_version,v_saved.request_digest)
                    IS DISTINCT FROM ROW(p_disposition,p_deposit,p_lease,p_amount,p_effective,p_reason,p_authorization,
                    p_termination_event,p_rule,p_expected_state_version,p_digest)
                THEN RAISE EXCEPTION 'Deposit idempotency key conflicts with another request' USING ERRCODE='23505'; END IF;
                RETURN v_result;
            END IF;
            IF p_disposition IS NULL OR p_disposition='00000000-0000-0000-0000-000000000000'
                OR p_termination_event IS NULL OR p_termination_event='00000000-0000-0000-0000-000000000000'
                OR p_amount IS NULL OR p_amount<=0 OR p_effective IS NULL OR NOT isfinite(p_effective)
                OR app.lease_notice_text_valid(p_reason,1000) IS NOT TRUE
                OR p_rule IS NULL OR p_rule NOT IN ('BR-DEP-022','BR-DEP-023')
                OR p_expected_state_version IS NULL OR p_expected_state_version<=0
            THEN RAISE EXCEPTION 'Deposit disposition context is invalid' USING ERRCODE='22023'; END IF;
            PERFORM 1 FROM app.leases lease JOIN app.units unit ON unit.id=lease.unit_id
                WHERE lease.id=p_lease AND unit.property_id=p_property FOR SHARE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Deposit Lease source was not found' USING ERRCODE='P0002'; END IF;
            PERFORM 1 FROM app.deposits WHERE id=p_deposit FOR UPDATE;
            IF NOT FOUND OR app.deposit_property_id(p_deposit) IS DISTINCT FROM p_property
            THEN RAISE EXCEPTION 'Deposit was not found' USING ERRCODE='P0002'; END IF;
            PERFORM app.serialize_deposit_state(p_deposit);
            SET CONSTRAINTS app.disposition_context_source_fk,app.disposition_context_command_fk DEFERRED;
            INSERT INTO app.lease_deposit_disposition_contexts(disposition_id,property_id,actor_id,idempotency_key,
                request_digest,deposit_id,lease_id,amount_usd_cents,effective_date,reason,authorization_reference,
                termination_event_id,governing_rule,expected_state_version)
            VALUES(p_disposition,p_property,p_actor,p_key,p_digest,p_deposit,p_lease,p_amount,p_effective,p_reason,
                p_authorization,p_termination_event,p_rule,p_expected_state_version);
            v_result:=app.record_lease_deposit_disposition(p_property,p_actor,p_key,p_digest,p_disposition,
                p_deposit,p_lease,p_amount,p_effective,p_reason,p_authorization);
            SET CONSTRAINTS app.disposition_context_source_fk,app.disposition_context_command_fk IMMEDIATE;
            RETURN v_result;
        EXCEPTION WHEN foreign_key_violation THEN
            RAISE EXCEPTION 'Deposit disposition context source was not found' USING ERRCODE='22023';
        END $$;

        CREATE FUNCTION app.validate_lease_deposit_disposition_context()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_context app.lease_deposit_disposition_contexts%ROWTYPE;
        BEGIN
            SELECT * INTO v_context FROM app.lease_deposit_disposition_contexts WHERE disposition_id=NEW.id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Approved Deposit disposition context is required' USING ERRCODE='22023'; END IF;
            PERFORM app.require_lease_deposit_disposition_context(v_context.property_id,NEW.actor_id,
                v_context.idempotency_key,v_context.request_digest,NEW.id,NEW.deposit_id,NEW.governing_lease_id,
                NEW.amount_usd_cents,NEW.effective_date,NEW.reason,NEW.authorization_reference);
            RETURN NEW;
        END $$;
        CREATE TRIGGER deposit_dispositions_require_context BEFORE INSERT ON app.deposit_dispositions
            FOR EACH ROW WHEN (NEW.governing_lease_id IS NOT NULL)
            EXECUTE FUNCTION app.validate_lease_deposit_disposition_context();
        CREATE TRIGGER lease_deposit_disposition_contexts_reject_mutation
            BEFORE UPDATE OR DELETE ON app.lease_deposit_disposition_contexts
            FOR EACH ROW EXECUTE FUNCTION app.reject_deposit_domain_history_loss();
        CREATE TRIGGER lease_deposit_disposition_contexts_reject_truncate
            BEFORE TRUNCATE ON app.lease_deposit_disposition_contexts
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_deposit_domain_history_loss();
        REVOKE ALL ON TABLE app.lease_deposit_disposition_contexts FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        REVOKE ALL ON FUNCTION app.require_lease_deposit_disposition_context(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text),
            app.validate_lease_deposit_disposition_context(),
            app.record_lease_deposit_disposition_with_context(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text,uuid,text,bigint)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.record_lease_deposit_disposition_with_context(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text,uuid,text,bigint) TO prm_financial;
    """)
    changes = (
        (
            "app.record_lease_deposit_disposition(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text)",
            "            IF p_amount_usd_cents IS NULL OR p_amount_usd_cents <= 0",
            """            PERFORM app.require_lease_deposit_disposition_context(
                p_property_id,p_actor_id,p_idempotency_key,p_request_digest,p_disposition_id,
                p_deposit_id,p_governing_lease_id,p_amount_usd_cents,p_effective_date,p_reason,p_authorization_reference);
            IF p_amount_usd_cents IS NULL OR p_amount_usd_cents <= 0""",
        ),
        (
            "app.validate_deposit_required_adjustment()",
            "            PERFORM 1 FROM app.deposits WHERE id = NEW.deposit_id FOR UPDATE;",
            """            -- Required corrections also invalidate retained Repeatable Read observations.
            PERFORM app.serialize_deposit_state(NEW.deposit_id);
            PERFORM 1 FROM app.deposits WHERE id = NEW.deposit_id FOR UPDATE;""",
        ),
    )
    for signature, before, after in changes:
        definition = (
            op.get_bind()
            .execute(
                text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
                {"signature": signature},
            )
            .scalar_one()
        )
        if definition.count(before) != 1:
            raise RuntimeError("Deposit disposition integration source contract changed")
        op.execute(definition.replace(before, after))


def downgrade() -> None:
    raise RuntimeError("Deposit disposition context is forward-only; preserve financial history")
