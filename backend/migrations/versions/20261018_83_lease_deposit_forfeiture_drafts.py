# ruff: noqa: E501
"""Lease Deposit forfeiture drafts (BR-DEP-018, 019, 022, 023, 026; BR-AUTH-010; V1-056 slice 6).

Owner answers to Q-2026-10-04-10 and Q-2026-10-04-11 (2026-10-04):
- Every Lease Deposit forfeiture is a DEPOSIT_FORFEITURE draft recorded under deposits.dispose
  and confirmed by a financial.approve holder; it forfeits the whole held amount and is never
  applied to what the Customer owes. The ground is worked out from the termination record:
  BR-LEASE-021 voluntary early (Security), BR-DEP-022 pet noncompliance (Security and Pet),
  BR-LEASE-005 unpaid Initial obligation (Security, moved in or not), BR-LEASE-025 non-pet
  violation (Security) and BR-LEASE-028 30-day default with a recorded Serious Default event on
  or before the termination date (Security). The BR-DEP-027 Pet Deposit outcome is built in the
  Final Settlement slices.
- The unpaid-Initial never-moved-in resolution (migration 70) no longer forfeits the Security
  Deposit (approved relaxing change), and defers the constraints again before each credit
  Adjustment so a two-line Initial Invoice can be credited (bug, Q-2026-10-04-10 a).
- A physical move-out correction is refused when a hand-back resolution relies on the record it
  would supersede (Q-2026-10-04-10 b; an owner-approved tightening).

Owner-approved tightening exceptions (answers to Q-2026-10-04-12 and Q-2026-10-04-13, Option A,
like the slice 3b revoke): the financial role loses EXECUTE on the one-call Lease Deposit
disposition functions and on the Lease disposition reversal. The functions stay unchanged; the
draft confirm still runs the disposition function as its owner. The forfeiture reversal draft is
built in slice 6b.
"""

from alembic import op
from sqlalchemy import text

revision = "20261018_83"
down_revision = "20261017_82"
branch_labels = None
depends_on = None

RECORD_WITH_CONTEXT = "app.record_lease_deposit_disposition_with_context(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text,uuid,text,bigint)"
REQUIRE_CONTEXT = "app.require_lease_deposit_disposition_context(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text)"
NEVER_MOVED_IN = "app.resolve_unpaid_initial_never_moved_in(uuid,uuid,uuid,text,uuid,uuid,text,text,text)"
PHYSICAL_MOVE_OUT = "app.physical_move_out_record(uuid,uuid,uuid,uuid,text,jsonb,text)"
SOURCE = "app.lease_deposit_forfeiture_source(uuid,uuid)"
RECORD_DRAFT = "app.record_lease_deposit_forfeiture_draft(uuid,uuid,uuid,uuid,uuid,text,text)"
CONFIRM_DRAFT = "app.confirm_lease_deposit_forfeiture_draft(uuid,uuid,uuid,uuid,text)"
RECORD_DIRECT = "app.record_lease_deposit_disposition(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text)"
REVERSE_DIRECT = "app.reverse_deposit_disposition_v2(uuid,uuid,uuid,text,uuid,uuid,text,text,text)"
# One-call paths that kept or released Lease Deposit money without a draft (BR-AUTH-010).
RETIRED = (RECORD_WITH_CONTEXT, RECORD_DIRECT, REVERSE_DIRECT)

PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        RECORD_WITH_CONTEXT,
        (
            (
                "OR p_rule IS NULL OR p_rule NOT IN ('BR-DEP-022','BR-DEP-023','BR-LEASE-005')",
                "OR p_rule IS NULL OR p_rule NOT IN ('BR-DEP-022','BR-DEP-023','BR-LEASE-005',\n"
                "                    'BR-LEASE-025','BR-LEASE-028')",
            ),
        ),
    ),
    (
        REQUIRE_CONTEXT,
        (
            (
                # BR-DEP-026: the Security Deposit is kept whether or not the Customer moved in.
                "                    OR EXISTS(SELECT 1 FROM app.occupancies WHERE lease_id=p_lease)\n"
                "                THEN RAISE EXCEPTION 'Unpaid Initial Security forfeiture source is invalid'",
                "                THEN RAISE EXCEPTION 'Unpaid Initial Security forfeiture source is invalid'",
            ),
            (
                "            ELSE RAISE EXCEPTION 'Unsupported Deposit disposition rule' USING ERRCODE='22023';",
                """            ELSIF v_context.governing_rule='BR-LEASE-025' THEN
                IF v_deposit.deposit_type IS DISTINCT FROM 'SECURITY'
                    OR v_event.governing_event_reference IS DISTINCT FROM 'BR-LEASE-025'
                    OR v_termination.command_event_id IS NULL
                    OR v_termination.context_data->>'basis' IS DISTINCT FROM 'CUSTOMER_VIOLATION'
                THEN RAISE EXCEPTION 'Violation Security forfeiture source is invalid' USING ERRCODE='22023'; END IF;
            ELSIF v_context.governing_rule='BR-LEASE-028' THEN
                IF v_deposit.deposit_type IS DISTINCT FROM 'SECURITY'
                    OR v_event.governing_event_reference IS DISTINCT FROM 'BR-LEASE-028'
                    OR NOT EXISTS(SELECT 1 FROM app.rent_nonpayment_events default_event
                        JOIN app.rent_nonpayment_cases nonpayment ON nonpayment.id=default_event.rent_nonpayment_case_id
                        WHERE nonpayment.lease_id=p_lease AND default_event.event_kind='THIRTY_DAY_SERIOUS_DEFAULT'
                          AND default_event.event_date<=p_effective)
                THEN RAISE EXCEPTION 'Thirty-day default Security forfeiture source is invalid' USING ERRCODE='22023'; END IF;
            ELSE RAISE EXCEPTION 'Unsupported Deposit disposition rule' USING ERRCODE='22023';""",
            ),
        ),
    ),
    (
        NEVER_MOVED_IN,
        (
            (
                """            SELECT * INTO v_deposit FROM app.deposits
            WHERE lease_id=v_lease.id AND deposit_type='SECURITY' FOR UPDATE;
            IF FOUND THEN
                v_held:=app.deposit_held_value_at(v_deposit.id,statement_timestamp());
                IF v_held>0 THEN
                    v_disposition:=gen_random_uuid();
                    PERFORM app.record_lease_deposit_disposition_with_context(p_property,p_actor,
                        app.unpaid_initial_derived_key(p_key,'deposit'),
                        app.unpaid_initial_derived_digest(p_digest,'deposit'),v_disposition,v_deposit.id,
                        v_lease.id,v_held,v_lease.actual_termination_date,p_reason,'deposits.dispose',p_event,
                        'BR-LEASE-005',app.deposit_disposition_state_version(v_deposit.id));
                END IF;
            END IF;
""",
                """            -- V1-056 slice 6 (owner answer to Q-2026-10-04-11): the Security Deposit is no longer
            -- forfeited here; staff record a forfeiture draft and a financial.approve holder confirms it.
""",
            ),
            (
                """                        v_adjustment:=gen_random_uuid();
                        PERFORM app.adjust_invoice(p_property,v_invoice.id,v_line.id,p_actor,
                            app.unpaid_initial_derived_key(p_key,'credit-' || v_step),""",
                """                        v_adjustment:=gen_random_uuid();
                        -- app.adjust_invoice ends with SET CONSTRAINTS ALL IMMEDIATE, which stays in force;
                        -- defer again so each call checks after its own Invoice update (Q-2026-10-04-10 a).
                        SET CONSTRAINTS ALL DEFERRED;
                        PERFORM app.adjust_invoice(p_property,v_invoice.id,v_line.id,p_actor,
                            app.unpaid_initial_derived_key(p_key,'credit-' || v_step),""",
            ),
        ),
    ),
    (
        PHYSICAL_MOVE_OUT,
        (
            (
                "                IF NOT FOUND THEN RAISE EXCEPTION 'Physical departure correction source not found' USING ERRCODE='P5N01'; END IF;",
                """                IF NOT FOUND THEN RAISE EXCEPTION 'Physical departure correction source not found' USING ERRCODE='P5N01'; END IF;
                -- Owner answer to Q-2026-10-04-10 (b): past decisions are never changed silently.
                IF EXISTS(SELECT 1 FROM app.hand_back_rent_resolutions WHERE physical_move_out_event_id=v_supersedes) THEN
                    RAISE EXCEPTION 'Hand-back resolution % relies on this move-out record',
                        (SELECT min(resolution.id::text) FROM app.hand_back_rent_resolutions resolution
                            WHERE resolution.physical_move_out_event_id=v_supersedes)
                        USING ERRCODE='P5N06';
                END IF;""",
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
            raise RuntimeError(f"Lease Deposit forfeiture source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    rule_checks = (
        op.get_bind()
        .execute(
            text(
                "SELECT conname FROM pg_catalog.pg_constraint "
                "WHERE conrelid='app.lease_deposit_disposition_contexts'::regclass AND contype='c' "
                "AND pg_catalog.pg_get_constraintdef(oid) LIKE '%governing_rule%BR-LEASE-005%'"
            )
        )
        .scalars()
        .all()
    )
    if len(rule_checks) != 1:
        raise RuntimeError("Deposit disposition rule constraint is not unique")
    # Relaxing: two more approved grounds.
    op.execute(f"""
        ALTER TABLE app.lease_deposit_disposition_contexts DROP CONSTRAINT {rule_checks[0]};
        ALTER TABLE app.lease_deposit_disposition_contexts ADD CONSTRAINT {rule_checks[0]}
            CHECK (governing_rule IN ('BR-DEP-022','BR-DEP-023','BR-LEASE-005','BR-LEASE-025','BR-LEASE-028'));
    """)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    op.execute("""
        -- Internal: the current forfeiture source of one Lease Deposit, worked out from the
        -- termination record (plan Q10), or a refusal.
        CREATE FUNCTION app.lease_deposit_forfeiture_source(p_property uuid,p_deposit uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_deposit app.deposits%ROWTYPE; v_lease app.leases%ROWTYPE; v_event app.lease_commands%ROWTYPE;
            v_basis text; v_rule text; v_held bigint; v_events bigint;
        BEGIN
            SELECT * INTO v_deposit FROM app.deposits WHERE id=p_deposit;
            IF NOT FOUND OR app.deposit_property_id(p_deposit) IS DISTINCT FROM p_property
                OR v_deposit.lease_id IS NULL
            THEN RAISE EXCEPTION 'Lease Deposit was not found' USING ERRCODE='P0002'; END IF;
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_deposit.lease_id;
            IF v_lease.status IS DISTINCT FROM 'TERMINATED' THEN
                RAISE EXCEPTION 'The Lease is not terminated' USING ERRCODE='22023'; END IF;
            SELECT count(*) INTO v_events FROM app.lease_commands event
            WHERE event.lease_id=v_lease.id AND event.property_id=p_property AND event.action='lease.terminate'
              AND event.occurred_at=v_lease.terminated_at;
            IF v_events<>1 THEN
                RAISE EXCEPTION 'The termination record is ambiguous' USING ERRCODE='22023'; END IF;
            SELECT event.* INTO STRICT v_event FROM app.lease_commands event
            WHERE event.lease_id=v_lease.id AND event.property_id=p_property AND event.action='lease.terminate'
              AND event.occurred_at=v_lease.terminated_at;
            SELECT context.context_data->>'basis' INTO v_basis FROM app.lease_termination_contexts context
            WHERE context.command_event_id=v_event.event_id;
            v_rule:=CASE
                WHEN v_event.governing_event_reference='BR-DEP-022' AND v_basis='CUSTOMER_VIOLATION'
                    THEN 'BR-DEP-022'
                WHEN v_deposit.deposit_type<>'SECURITY' THEN NULL
                WHEN v_event.governing_event_reference='BR-LEASE-021'
                    AND v_lease.actual_termination_date<v_lease.end_date
                    AND (v_basis IS NULL OR v_basis='VOLUNTARY_EARLY') THEN 'BR-DEP-023'
                WHEN v_event.governing_event_reference='BR-LEASE-005' AND v_basis='UNPAID_INITIAL_OBLIGATION'
                    THEN 'BR-LEASE-005'
                WHEN v_event.governing_event_reference='BR-LEASE-025' AND v_basis='CUSTOMER_VIOLATION'
                    THEN 'BR-LEASE-025'
                WHEN v_event.governing_event_reference='BR-LEASE-028' AND EXISTS(
                    SELECT 1 FROM app.rent_nonpayment_events default_event
                    JOIN app.rent_nonpayment_cases nonpayment ON nonpayment.id=default_event.rent_nonpayment_case_id
                    WHERE nonpayment.lease_id=v_lease.id AND default_event.event_kind='THIRTY_DAY_SERIOUS_DEFAULT'
                      AND default_event.event_date<=v_lease.actual_termination_date) THEN 'BR-LEASE-028'
            END;
            IF v_rule IS NULL AND v_deposit.deposit_type<>'SECURITY' THEN
                RAISE EXCEPTION 'The Pet Deposit is not forfeited on this ground; it is decided at Final Settlement (BR-DEP-024, BR-DEP-027)'
                    USING ERRCODE='22023'; END IF;
            IF v_rule IS NULL THEN
                RAISE EXCEPTION 'The forfeiture ground cannot be worked out from the termination record'
                    USING ERRCODE='22023'; END IF;
            v_held:=app.deposit_held_value_at(p_deposit,statement_timestamp());
            IF v_held<=0 THEN RAISE EXCEPTION 'The Deposit holds nothing to forfeit' USING ERRCODE='22023'; END IF;
            RETURN jsonb_build_object('variant','LEASE_FORFEITURE','deposit_id',p_deposit,
                'deposit_type',v_deposit.deposit_type,'lease_id',v_lease.id,
                'termination_event_id',v_event.event_id,'governing_rule',v_rule,
                'effective_date',v_lease.actual_termination_date,'amount_usd_cents',v_held,
                'state_version',app.deposit_disposition_state_version(p_deposit));
        END $$;

        -- Staff record the forfeiture of the whole held Deposit as a draft (deposits.dispose).
        CREATE FUNCTION app.record_lease_deposit_forfeiture_draft(p_property uuid,p_actor uuid,p_draft uuid,
            p_deposit uuid,p_disposition uuid,p_reason text,p_authorization text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_input jsonb; v_source jsonb; v_existing app.financial_drafts%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property,p_actor);
            PERFORM app.assert_active_financial_actor(p_actor,p_property);
            IF p_authorization IS DISTINCT FROM 'deposits.dispose' THEN
                RAISE EXCEPTION 'Lease Deposit forfeiture draft authorization is invalid' USING ERRCODE='42501'; END IF;
            IF p_draft IS NULL OR p_draft='00000000-0000-0000-0000-000000000000' OR p_deposit IS NULL
                OR p_disposition IS NULL OR p_disposition='00000000-0000-0000-0000-000000000000'
                OR p_disposition=p_draft
                -- The same reason check the disposition function applies at confirmation.
                OR app.lease_notice_text_valid(p_reason,1000) IS NOT TRUE
            THEN RAISE EXCEPTION 'Lease Deposit forfeiture draft input is invalid' USING ERRCODE='22023'; END IF;
            v_input:=jsonb_build_object('variant','LEASE_FORFEITURE','deposit_id',p_deposit,
                'disposition_id',p_disposition,'reason',p_reason);
            -- An exact repeat replays before any current-state check.
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
            SELECT * INTO v_existing FROM app.financial_drafts WHERE id=p_draft;
            IF FOUND THEN
                IF v_existing.property_id=p_property AND v_existing.kind='DEPOSIT_FORFEITURE'
                    AND v_existing.prepared_by=p_actor
                    AND jsonb_build_object('variant',v_existing.payload->'variant',
                        'deposit_id',v_existing.payload->'deposit_id',
                        'disposition_id',v_existing.payload->'disposition_id',
                        'reason',v_existing.payload->'reason')=v_input
                THEN RETURN app.financial_draft_json(v_existing); END IF;
                RAISE EXCEPTION 'Lease Deposit forfeiture draft identity was reused' USING ERRCODE='P5205';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || p_deposit::text,0));
            v_source:=app.lease_deposit_forfeiture_source(p_property,p_deposit);
            IF EXISTS (SELECT 1 FROM app.financial_drafts draft
                WHERE draft.property_id=p_property AND draft.kind='DEPOSIT_FORFEITURE'
                  AND draft.payload->>'variant'='LEASE_FORFEITURE'
                  AND draft.payload->>'deposit_id'=p_deposit::text
                  AND NOT EXISTS (SELECT 1 FROM app.financial_draft_decisions decision WHERE decision.draft_id=draft.id))
            THEN RAISE EXCEPTION 'A forfeiture draft for this Deposit is already waiting' USING ERRCODE='55000'; END IF;
            -- A disposition id is used once: by a recorded disposition or by any forfeiture draft.
            IF EXISTS (SELECT 1 FROM app.deposit_dispositions WHERE id=p_disposition)
                OR EXISTS (SELECT 1 FROM app.financial_drafts draft
                    WHERE draft.kind='DEPOSIT_FORFEITURE'
                      AND draft.payload->>'disposition_id'=p_disposition::text)
            THEN RAISE EXCEPTION 'Deposit disposition identity was reused' USING ERRCODE='P5205'; END IF;
            RETURN app.insert_financial_draft(p_property,p_actor,p_draft,'DEPOSIT_FORFEITURE','deposits.dispose',
                v_input || (v_source - ARRAY['variant','deposit_id']),
                'deposit-state:' || (v_source->>'state_version'),p_reason);
        END $$;

        -- A financial.approve holder confirms: the existing disposition function runs with the
        -- approver as actor, so every earlier Deposit rule applies.
        CREATE FUNCTION app.confirm_lease_deposit_forfeiture_draft(p_property uuid,p_actor uuid,p_deposit uuid,
            p_draft uuid,p_authorization text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE; v_source jsonb; v_snapshot jsonb; v_digest text;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property,p_actor);
            PERFORM app.assert_active_financial_actor(p_actor,p_property);
            IF p_authorization IS DISTINCT FROM 'financial.approve' THEN
                RAISE EXCEPTION 'Only financial.approve may confirm a forfeiture draft' USING ERRCODE='42501'; END IF;
            IF p_draft IS NULL OR p_deposit IS NULL THEN
                RAISE EXCEPTION 'Lease Deposit forfeiture confirmation is invalid' USING ERRCODE='22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
            SELECT draft.* INTO v_draft FROM app.financial_drafts draft
            JOIN app.financial_draft_decisions decision ON decision.draft_id=draft.id
            WHERE draft.id=p_draft AND draft.property_id=p_property AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_actor AND draft.payload->>'variant'='LEASE_FORFEITURE'
              AND draft.payload->>'deposit_id'=p_deposit::text;
            IF FOUND THEN
                -- An exact replay returns the stored result of the first confirmation.
                SELECT command.result_snapshot INTO STRICT v_snapshot FROM app.deposit_commands command
                WHERE command.actor_id=p_actor AND command.property_id=p_property
                  AND command.action='deposit.disposition.record' AND command.idempotency_key=p_draft;
                RETURN jsonb_build_object('draft',app.financial_draft_json(v_draft),'deposit',v_snapshot);
            END IF;
            v_draft:=app.lock_pending_financial_draft(p_property,p_draft);
            IF v_draft.kind<>'DEPOSIT_FORFEITURE' OR v_draft.prepare_capability<>'deposits.dispose'
                OR v_draft.payload->>'variant' IS DISTINCT FROM 'LEASE_FORFEITURE'
                OR v_draft.payload->>'deposit_id' IS DISTINCT FROM p_deposit::text
            THEN RAISE EXCEPTION 'Financial draft was not found' USING ERRCODE='P0002'; END IF;
            IF EXISTS (SELECT 1 FROM app.deposit_commands command
                WHERE command.actor_id=p_actor AND command.property_id=p_property
                  AND command.action='deposit.disposition.record' AND command.idempotency_key=p_draft)
            THEN RAISE EXCEPTION 'Lease Deposit forfeiture draft identity was reused' USING ERRCODE='P5205'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('lease-deposit-forfeiture:' || p_deposit::text,0));
            v_source:=app.lease_deposit_forfeiture_source(p_property,p_deposit);
            -- A draft is stale when the Deposit, its held amount or the ground changed.
            IF (v_source->>'state_version') IS DISTINCT FROM (v_draft.payload->>'state_version')
                OR (v_source->>'amount_usd_cents') IS DISTINCT FROM (v_draft.payload->>'amount_usd_cents')
                OR (v_source->>'governing_rule') IS DISTINCT FROM (v_draft.payload->>'governing_rule')
                OR (v_source->>'termination_event_id') IS DISTINCT FROM (v_draft.payload->>'termination_event_id')
            THEN RAISE EXCEPTION 'Lease Deposit forfeiture draft is stale' USING ERRCODE='23514'; END IF;
            v_digest:=encode(sha256(convert_to('lease-deposit-forfeiture-draft:' || p_draft::text,'UTF8')),'hex');
            PERFORM app.record_lease_deposit_disposition_with_context(p_property,p_actor,p_draft,v_digest,
                (v_draft.payload->>'disposition_id')::uuid,p_deposit,(v_draft.payload->>'lease_id')::uuid,
                (v_draft.payload->>'amount_usd_cents')::bigint,(v_draft.payload->>'effective_date')::date,
                v_draft.payload->>'reason','deposits.dispose',(v_draft.payload->>'termination_event_id')::uuid,
                v_draft.payload->>'governing_rule',(v_draft.payload->>'state_version')::bigint);
            SELECT command.result_snapshot INTO STRICT v_snapshot FROM app.deposit_commands command
            WHERE command.actor_id=p_actor AND command.property_id=p_property
              AND command.action='deposit.disposition.record' AND command.idempotency_key=p_draft;
            PERFORM app.confirm_financial_draft_record(p_property,p_actor,p_draft,'DEPOSIT_FORFEITURE',
                jsonb_build_object('deposit_id',p_deposit,'disposition_id',v_draft.payload->>'disposition_id',
                    'governing_rule',v_draft.payload->>'governing_rule'),'financial.approve');
            RETURN jsonb_build_object('draft',app.financial_draft_json(v_draft),'deposit',v_snapshot);
        END $$;
    """)
    for function in (SOURCE, RECORD_DRAFT, CONFIRM_DRAFT):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD_DRAFT}, {CONFIRM_DRAFT} TO prm_financial")
    for function in RETIRED:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {function} FROM prm_financial")


def downgrade() -> None:
    raise RuntimeError("Lease Deposit forfeiture draft migration is forward-only")
