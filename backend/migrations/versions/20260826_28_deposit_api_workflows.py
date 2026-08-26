# ruff: noqa: E501
"""Split active-Lease Pet Deposit departure and qualification commands."""

from alembic import op

revision = "20260826_28"
down_revision = "20260826_27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install the bounded V1-038 qualification command boundary."""
    op.execute(
        """
        ALTER TABLE app.deposit_commands
            DROP CONSTRAINT deposit_commands_action_check,
            ADD CONSTRAINT deposit_commands_action_check CHECK (action IN (
                'deposit.pet.create', 'deposit.required.adjust', 'deposit.receipt.reverse',
                'deposit.disposition.record', 'deposit.disposition.reverse',
                'deposit.pet_refund.qualify', 'deposit.pet_departure.record',
                'deposit.pet_refund.review', 'deposit.reservation_disposition.correct'
            ));

        CREATE FUNCTION app.deposit_has_active_application(p_deposit_id uuid)
        RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_active boolean;
        BEGIN
            IF pg_catalog.to_regclass('app.deposit_applications') IS NULL THEN
                RETURN false;
            END IF;
            IF pg_catalog.to_regclass('app.deposit_application_reversals') IS NULL THEN
                EXECUTE
                    'SELECT EXISTS (SELECT 1 FROM app.deposit_applications '
                    'WHERE deposit_id=$1)'
                    INTO v_active USING p_deposit_id;
            ELSE
                EXECUTE
                    'SELECT EXISTS ('
                    'SELECT 1 FROM app.deposit_applications AS application '
                    'WHERE application.deposit_id=$1 AND NOT EXISTS ('
                    'SELECT 1 FROM app.deposit_application_reversals AS reversal '
                    'WHERE reversal.deposit_application_id=application.id))'
                    INTO v_active USING p_deposit_id;
            END IF;
            RETURN COALESCE(v_active,false);
        END;
        $$;

        CREATE FUNCTION app.deposit_resource_snapshot(p_deposit_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT snapshot.value || jsonb_build_object(
                'pet_departure_id', departure.id,
                'pet_refund_review_id', review.id,
                'refund_qualified', review.id IS NOT NULL,
                'reservation_version', reservation.version,
                'deposit_disposition_id', disposition.id,
                'deposit_disposition_reversal_id', reversal.id
            )
            FROM (SELECT app.deposit_snapshot(p_deposit_id) AS value) AS snapshot
            LEFT JOIN app.reservations AS reservation
              ON reservation.id=(snapshot.value ->> 'reservation_id')::uuid
            LEFT JOIN LATERAL (
                SELECT event.id
                FROM app.lease_pet_departures AS event
                JOIN app.deposits AS deposit ON deposit.pet_approval_id=event.pet_approval_id
                WHERE deposit.id=p_deposit_id
                ORDER BY event.occurred_at DESC,event.id DESC LIMIT 1
            ) AS departure ON true
            LEFT JOIN LATERAL (
                SELECT event.id
                FROM app.pet_deposit_refund_reviews AS event
                WHERE event.pet_deposit_id=p_deposit_id
                ORDER BY event.reviewed_at DESC,event.id DESC LIMIT 1
            ) AS review ON true
            LEFT JOIN LATERAL (
                SELECT event.id
                FROM app.deposit_dispositions AS event
                WHERE event.deposit_id=p_deposit_id
                ORDER BY event.occurred_at DESC,event.id DESC LIMIT 1
            ) AS disposition ON true
            LEFT JOIN LATERAL (
                SELECT event.id
                FROM app.deposit_disposition_reversals AS event
                JOIN app.deposit_dispositions AS source
                  ON source.id=event.deposit_disposition_id
                WHERE source.deposit_id=p_deposit_id
                ORDER BY event.occurred_at DESC,event.id DESC LIMIT 1
            ) AS reversal ON true
            WHERE snapshot.value IS NOT NULL
        $$;

        CREATE FUNCTION app.pet_refund_review_resource_snapshot(p_review_id uuid)
        RETURNS TABLE(
            review_id uuid,
            departure_id uuid,
            deposit_id uuid,
            obligations_reviewed_usd_cents bigint,
            review_findings text,
            resolution_reference text,
            reason text,
            reviewed_at timestamptz,
            reviewed_by uuid,
            authorization_reference text,
            refundable_usd_cents bigint,
            current_refundable_usd_cents bigint
        ) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT review.id,review.pet_departure_id,review.pet_deposit_id,
                review.obligations_reviewed_usd_cents,review.review_findings,
                review.resolution_reference,review.reason,review.reviewed_at,
                review.reviewed_by,review.authorization_reference,
                (command.result_snapshot->>'held_refundable_usd_cents')::bigint,
                (app.deposit_snapshot(review.pet_deposit_id)
                    ->>'held_refundable_usd_cents')::bigint
            FROM app.pet_deposit_refund_reviews AS review
            JOIN LATERAL (
                SELECT source.result_snapshot
                FROM app.deposit_commands AS source
                WHERE source.deposit_id=review.pet_deposit_id
                  AND source.action IN (
                      'deposit.pet_refund.review','deposit.pet_refund.qualify'
                  )
                  AND source.result_snapshot->>'pet_refund_review_id'=review.id::text
                ORDER BY source.created_at DESC LIMIT 1
            ) AS command ON true
            WHERE review.id=p_review_id
        $$;

        CREATE FUNCTION app.record_deposit_audit(
            p_event_id uuid, p_action text, p_entity_type text, p_entity_id uuid,
            p_deposit_id uuid, p_reason text, p_authorization_reference text,
            p_actor_id uuid, p_correlation_id uuid, p_resulting_state jsonb,
            p_linked_source_event_id uuid DEFAULT NULL
        ) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_recorded_id uuid;
        BEGIN
            INSERT INTO app.audit_events(
                id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,resulting_state,
                correlation_id,source,outcome,linked_source_event_id,customer_id,
                unit_id,lease_id
            )
            SELECT p_event_id,statement_timestamp(),
                timezone(property.timezone_name,statement_timestamp())::date,
                p_actor_id,btrim(p_action),btrim(p_entity_type),p_entity_id,
                btrim(p_reason),btrim(p_authorization_reference),property.id,
                p_resulting_state,p_correlation_id,'API','SUCCEEDED',
                p_linked_source_event_id,deposit.customer_id,unit.id,deposit.lease_id
            FROM app.deposits AS deposit
            LEFT JOIN app.reservations AS reservation ON reservation.id=deposit.reservation_id
            LEFT JOIN app.leases AS lease ON lease.id=deposit.lease_id
            JOIN app.units AS unit ON unit.id=COALESCE(reservation.unit_id,lease.unit_id)
            JOIN app.properties AS property ON property.id=unit.property_id
            WHERE deposit.id=p_deposit_id
            ON CONFLICT (id) DO NOTHING
            RETURNING audit_events.id INTO v_recorded_id;
            IF v_recorded_id IS NULL THEN
                SELECT audit.id INTO v_recorded_id
                FROM app.audit_events AS audit
                JOIN app.deposits AS deposit ON deposit.id=p_deposit_id
                LEFT JOIN app.reservations AS reservation
                  ON reservation.id=deposit.reservation_id
                LEFT JOIN app.leases AS lease ON lease.id=deposit.lease_id
                JOIN app.units AS unit
                  ON unit.id=COALESCE(reservation.unit_id,lease.unit_id)
                WHERE audit.id=p_event_id
                  AND audit.actor_id=p_actor_id
                  AND audit.action=btrim(p_action)
                  AND audit.entity_type=btrim(p_entity_type)
                  AND audit.entity_id=p_entity_id
                  AND audit.reason=btrim(p_reason)
                  AND audit.authorization_reference=btrim(p_authorization_reference)
                  AND audit.property_id=unit.property_id
                  AND audit.resulting_state=p_resulting_state
                  AND audit.correlation_id=p_correlation_id
                  AND audit.source='API'
                  AND audit.outcome='SUCCEEDED'
                  AND audit.linked_source_event_id IS NOT DISTINCT FROM
                      p_linked_source_event_id
                  AND audit.customer_id IS NOT DISTINCT FROM deposit.customer_id
                  AND audit.unit_id IS NOT DISTINCT FROM unit.id
                  AND audit.lease_id IS NOT DISTINCT FROM deposit.lease_id;
                IF v_recorded_id IS NULL THEN
                    RAISE EXCEPTION 'Deposit audit identity conflicts with existing evidence'
                        USING ERRCODE='23505';
                END IF;
            END IF;
        END;
        $$;

        CREATE FUNCTION app.record_active_lease_pet_departure(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_departure_id uuid, p_deposit_id uuid,
            p_permanently_left_date date, p_reason text,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_result jsonb; v_lease_id uuid; v_approval_id uuid;
            v_approved_date date; v_lease_start_date date; v_business_date date;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                p_property_id::text || ':' || p_actor_id::text ||
                '-deposit.pet_departure.record-' || p_idempotency_key::text, 0));
            v_result := app.replay_deposit_command(p_property_id,p_actor_id,
                'deposit.pet_departure.record',p_idempotency_key,p_request_digest);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_authorization_reference <> 'deposits.refund.qualify'
                OR COALESCE(btrim(p_reason),'') = ''
            THEN RAISE EXCEPTION 'Pet departure evidence is invalid' USING ERRCODE='22023'; END IF;
            SELECT deposit.lease_id,deposit.pet_approval_id,approval.approved_date,
                   lease.start_date,
                   timezone(property.timezone_name,statement_timestamp())::date
            INTO v_lease_id,v_approval_id,v_approved_date,v_lease_start_date,v_business_date
            FROM app.deposits AS deposit
            JOIN app.leases AS lease ON lease.id=deposit.lease_id
            JOIN app.lease_pet_approvals AS approval ON approval.id=deposit.pet_approval_id
            JOIN app.units AS unit ON unit.id=lease.unit_id
            JOIN app.properties AS property ON property.id=unit.property_id
            WHERE deposit.id=p_deposit_id AND deposit.deposit_type='PET'
              AND lease.status='SIGNED' AND unit.property_id=p_property_id
            FOR UPDATE OF deposit;
            IF NOT FOUND THEN RAISE EXCEPTION 'Eligible Pet Deposit was not found' USING ERRCODE='P0002'; END IF;
            IF p_permanently_left_date < GREATEST(v_approved_date,v_lease_start_date)
                OR p_permanently_left_date > v_business_date
            THEN RAISE EXCEPTION 'Pet departure chronology is invalid' USING ERRCODE='23514'; END IF;
            INSERT INTO app.lease_pet_departures(
                id,pet_approval_id,lease_id,permanently_left_date,reason,occurred_at,actor_id
            ) VALUES (
                p_departure_id,v_approval_id,v_lease_id,p_permanently_left_date,
                btrim(p_reason),statement_timestamp(),p_actor_id
            );
            SET CONSTRAINTS app.lease_pet_departures_validate IMMEDIATE;
            v_result := app.deposit_snapshot(p_deposit_id)
                || jsonb_build_object('pet_departure_id',p_departure_id,'refund_qualified',false);
            PERFORM app.record_deposit_command(p_property_id,p_actor_id,
                'deposit.pet_departure.record',p_idempotency_key,p_request_digest,
                p_deposit_id,p_reason,p_authorization_reference,v_result);
            PERFORM app.record_deposit_audit(
                p_departure_id,'deposit.pet_departure.recorded','pet_departure',
                p_departure_id,p_deposit_id,p_reason,p_authorization_reference,
                p_actor_id,p_idempotency_key,v_result,v_approval_id
            );
            RETURN v_result;
        END;
        $$;

        CREATE FUNCTION app.qualify_active_lease_pet_refund_review(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_review_id uuid, p_departure_id uuid,
            p_deposit_id uuid, p_obligations_reviewed_usd_cents bigint,
            p_review_findings text, p_resolution_reference text, p_reason text,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_result jsonb;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                p_property_id::text || ':' || p_actor_id::text ||
                '-deposit.pet_refund.review-' || p_idempotency_key::text, 0));
            v_result := app.replay_deposit_command(p_property_id,p_actor_id,
                'deposit.pet_refund.review',p_idempotency_key,p_request_digest);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_authorization_reference <> 'deposits.refund.qualify'
                OR p_obligations_reviewed_usd_cents < 0
                OR COALESCE(btrim(p_review_findings),'') = ''
                OR COALESCE(btrim(p_resolution_reference),'') = ''
                OR COALESCE(btrim(p_reason),'') = ''
            THEN RAISE EXCEPTION 'Pet Deposit Refund review is invalid' USING ERRCODE='22023'; END IF;
            PERFORM 1
            FROM app.deposits AS deposit
            JOIN app.leases AS lease ON lease.id=deposit.lease_id
            JOIN app.lease_pet_departures AS departure
              ON departure.id=p_departure_id
             AND departure.lease_id=lease.id
             AND departure.pet_approval_id=deposit.pet_approval_id
            JOIN app.units AS unit ON unit.id=lease.unit_id
            WHERE deposit.id=p_deposit_id AND deposit.deposit_type='PET'
              AND lease.status='SIGNED' AND unit.property_id=p_property_id
            FOR UPDATE OF deposit;
            IF NOT FOUND THEN RAISE EXCEPTION 'Eligible Pet departure was not found' USING ERRCODE='P0002'; END IF;
            IF (app.deposit_snapshot(p_deposit_id)->>'held_refundable_usd_cents')::bigint <= 0
            THEN RAISE EXCEPTION 'Pet Deposit has no refundable held balance' USING ERRCODE='23514'; END IF;
            INSERT INTO app.pet_deposit_refund_reviews(
                id,pet_departure_id,pet_deposit_id,obligations_reviewed_usd_cents,
                review_findings,all_pet_obligations_resolved,resolution_reference,
                reason,reviewed_at,reviewed_by,authorization_reference
            ) VALUES (
                p_review_id,p_departure_id,p_deposit_id,p_obligations_reviewed_usd_cents,
                btrim(p_review_findings),true,btrim(p_resolution_reference),btrim(p_reason),
                statement_timestamp(),p_actor_id,p_authorization_reference
            );
            SET CONSTRAINTS app.pet_deposit_refund_reviews_validate IMMEDIATE;
            v_result := app.deposit_snapshot(p_deposit_id)
                || jsonb_build_object('pet_departure_id',p_departure_id,
                    'pet_refund_review_id',p_review_id,'refund_qualified',true);
            PERFORM app.record_deposit_command(p_property_id,p_actor_id,
                'deposit.pet_refund.review',p_idempotency_key,p_request_digest,
                p_deposit_id,p_reason,p_authorization_reference,v_result);
            PERFORM app.record_deposit_audit(
                p_review_id,'deposit.pet_refund.reviewed','pet_refund_review',
                p_review_id,p_deposit_id,p_reason,p_authorization_reference,
                p_actor_id,p_idempotency_key,v_result,p_departure_id
            );
            RETURN v_result;
        END;
        $$;

        CREATE FUNCTION app.create_pet_deposit_v2(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_deposit_id uuid, p_lease_id uuid,
            p_pet_approval_id uuid, p_required_usd_cents bigint,
            p_required_effective_date date, p_reason text,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_result jsonb;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                p_property_id::text || ':' || p_actor_id::text ||
                '-deposit.pet.create-' || p_idempotency_key::text, 0));
            v_result := app.create_pet_deposit(
                p_property_id,p_actor_id,p_idempotency_key,p_request_digest,p_deposit_id,
                p_lease_id,p_pet_approval_id,p_required_usd_cents,p_required_effective_date,
                p_reason,p_authorization_reference
            );
            PERFORM app.record_deposit_audit(
                p_deposit_id,'deposit.pet.created','deposit',p_deposit_id,
                p_deposit_id,p_reason,p_authorization_reference,p_actor_id,
                p_idempotency_key,v_result,p_pet_approval_id
            );
            RETURN v_result;
        END;
        $$;

        CREATE FUNCTION app.reverse_deposit_receipt_v2(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_reversal_id uuid, p_receipt_id uuid,
            p_reason text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_result jsonb; v_response jsonb; v_deposit_id uuid;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                p_property_id::text || ':' || p_actor_id::text ||
                '-deposit.receipt.reverse-' || p_idempotency_key::text, 0));
            SELECT receipt.deposit_id INTO STRICT v_deposit_id
            FROM app.deposit_receipts AS receipt WHERE receipt.id=p_receipt_id;
            v_result := app.replay_deposit_command(
                p_property_id,p_actor_id,'deposit.receipt.reverse',
                p_idempotency_key,p_request_digest
            );
            IF v_result IS NOT NULL THEN
                SELECT audit.resulting_state INTO v_response
                FROM app.audit_events AS audit
                WHERE audit.id=p_reversal_id
                  AND audit.actor_id=p_actor_id
                  AND audit.action='deposit.receipt.reversed'
                  AND audit.correlation_id=p_idempotency_key;
                RETURN COALESCE(v_response,v_result);
            END IF;
            PERFORM 1 FROM app.deposits WHERE id=v_deposit_id FOR UPDATE;
            IF app.deposit_has_active_application(v_deposit_id) THEN
                RAISE EXCEPTION 'Deposit receipt has active dependent financial history'
                    USING ERRCODE='55000';
            END IF;
            v_result := app.reverse_deposit_receipt(
                p_property_id,p_actor_id,p_idempotency_key,p_request_digest,
                p_reversal_id,p_receipt_id,p_reason,p_authorization_reference
            );
            v_response := app.deposit_resource_snapshot(v_deposit_id);
            PERFORM app.record_deposit_audit(
                p_reversal_id,'deposit.receipt.reversed','deposit_receipt_reversal',
                p_reversal_id,v_deposit_id,p_reason,p_authorization_reference,
                p_actor_id,p_idempotency_key,v_response,p_receipt_id
            );
            RETURN v_response;
        END;
        $$;

        CREATE FUNCTION app.reverse_deposit_disposition_v2(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_reversal_id uuid, p_disposition_id uuid,
            p_reason text, p_evidence_reference text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_result jsonb; v_response jsonb; v_deposit_id uuid;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                p_property_id::text || ':' || p_actor_id::text ||
                '-deposit.disposition.reverse-' || p_idempotency_key::text, 0));
            SELECT disposition.deposit_id INTO STRICT v_deposit_id
            FROM app.deposit_dispositions AS disposition
            WHERE disposition.id=p_disposition_id;
            v_result := app.replay_deposit_command(
                p_property_id,p_actor_id,'deposit.disposition.reverse',
                p_idempotency_key,p_request_digest
            );
            IF v_result IS NOT NULL THEN
                SELECT audit.resulting_state INTO v_response
                FROM app.audit_events AS audit
                WHERE audit.id=p_reversal_id
                  AND audit.actor_id=p_actor_id
                  AND audit.action='deposit.disposition.reversed'
                  AND audit.correlation_id=p_idempotency_key;
                RETURN COALESCE(v_response,v_result);
            END IF;
            v_result := app.reverse_deposit_disposition(
                p_property_id,p_actor_id,p_idempotency_key,p_request_digest,p_reversal_id,
                p_disposition_id,p_reason,p_evidence_reference,p_authorization_reference
            );
            v_response := app.deposit_resource_snapshot(v_deposit_id);
            PERFORM app.record_deposit_audit(
                p_reversal_id,'deposit.disposition.reversed',
                'deposit_disposition_reversal',p_reversal_id,v_deposit_id,
                p_reason,p_authorization_reference,p_actor_id,p_idempotency_key,
                v_response,p_disposition_id
            );
            RETURN v_response;
        END;
        $$;

        CREATE FUNCTION app.correct_reservation_deposit_disposition_v2(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_correction_id uuid, p_expected_outcome_id uuid,
            p_replacement_outcome_id uuid, p_reservation_id uuid,
            p_expected_version integer, p_reason text, p_evidence_reference text,
            p_correction_authorization_reference text,
            p_replacement_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_result jsonb; v_deposit_id uuid;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                p_property_id::text || ':' || p_actor_id::text ||
                '-deposit.reservation_disposition.correct-' || p_idempotency_key::text, 0));
            v_result := app.replay_deposit_command(
                p_property_id,p_actor_id,'deposit.reservation_disposition.correct',
                p_idempotency_key,p_request_digest
            );
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            PERFORM * FROM app.correct_reservation_deposit_outcome(
                p_property_id,p_idempotency_key,p_request_digest,p_correction_id,
                p_expected_outcome_id,p_replacement_outcome_id,NULL,p_reservation_id,
                p_expected_version,p_reason,p_evidence_reference,
                p_correction_authorization_reference,p_replacement_authorization_reference,
                p_actor_id
            );
            SELECT deposit.id INTO STRICT v_deposit_id
            FROM app.deposits AS deposit
            WHERE deposit.reservation_id=p_reservation_id;
            v_result := app.deposit_resource_snapshot(v_deposit_id);
            PERFORM app.record_deposit_command(
                p_property_id,p_actor_id,'deposit.reservation_disposition.correct',
                p_idempotency_key,p_request_digest,v_deposit_id,p_reason,
                p_correction_authorization_reference,v_result
            );
            RETURN v_result;
        END;
        $$;

        """
    )
    functions = (
        "app.record_active_lease_pet_departure(uuid,uuid,uuid,text,uuid,uuid,date,text,text)",
        "app.qualify_active_lease_pet_refund_review(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,text,text,text,text)",
        "app.create_pet_deposit_v2(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text)",
        "app.reverse_deposit_receipt_v2(uuid,uuid,uuid,text,uuid,uuid,text,text)",
        "app.reverse_deposit_disposition_v2(uuid,uuid,uuid,text,uuid,uuid,text,text,text)",
        "app.correct_reservation_deposit_disposition_v2(uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,integer,text,text,text,text)",
    )
    for function in functions:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "app.record_deposit_audit(uuid,text,text,uuid,uuid,text,text,uuid,uuid,jsonb,uuid) "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    superseded_functions = (
        "app.create_pet_deposit(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text)",
        "app.reverse_deposit_receipt(uuid,uuid,uuid,text,uuid,uuid,text,text)",
        "app.reverse_deposit_disposition(uuid,uuid,uuid,text,uuid,uuid,text,text,text)",
        "app.qualify_active_lease_pet_refund(uuid,uuid,uuid,text,uuid,uuid,uuid,date,bigint,text,text,text,text)",
    )
    for function in superseded_functions:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(
        "REVOKE ALL ON FUNCTION app.deposit_has_active_application(uuid) "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.deposit_has_active_application(uuid) "
        "TO prm_runtime, prm_financial"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.deposit_resource_snapshot(uuid) "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.deposit_resource_snapshot(uuid) "
        "TO prm_runtime, prm_financial"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.pet_refund_review_resource_snapshot(uuid) "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.pet_refund_review_resource_snapshot(uuid) "
        "TO prm_runtime, prm_financial"
    )


def downgrade() -> None:
    """Refuse rollback that could erase Deposit workflow history."""
    raise RuntimeError("Deposit API workflow migration is forward-only")
