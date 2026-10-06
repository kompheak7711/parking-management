# ruff: noqa: E501
"""Post-settlement correction record (V1-056 sub-slice 10a).

BR-SETTLE-012, BR-SETTLE-013, BR-AUTH-010; DB-SETTLE-003, DB-SETTLE-005 (amended by owner answer 2
to Q-2026-10-06-36); owner answers to Q-2026-10-06-36.

- A closed Final Settlement is never reopened: a later fix is a new correction linked to it, with
  a reason, prepared by Staff under final_settlements.prepare as a SETTLEMENT_CORRECTION draft and
  confirmed only by a financial.approve holder; there is no time limit.
- app.settlement_corrections (DB-SETTLE-003) is the header: the closed Settlement, the reason, the
  approver, financial.approve and the draft as correlation id. It carries no amount.
- app.settlement_correction_effects (DB-SETTLE-005) links the header to each ordinary financial
  record the correction writes, through exactly one typed foreign key per row. The links are
  deferrable, so a writer links a record before it writes it, and unique, so a record is the
  effect of at most one correction. An effect is accepted only for a correction confirmed in the
  same transaction.
- "The same transaction" is exact: app.begin_settlement_correction stores the top-level
  transaction id (pg_current_xact_id(), the same inside an exception block) in the CONFIRMED
  decision's result, and the checks compare it with the current one (review round 1, blocker B1:
  a time comparison alone let a concurrent transaction see another's committed correction as its
  own). They also need the decision written after the current transaction started (review round
  2: after a logical restore into a new cluster a stored transaction id can be handed out again).
- app.begin_settlement_correction records the draft's CONFIRMED decision and then the header;
  app.link_settlement_correction_effect adds an effect. Both are internal: only the variant
  writers of the later sub-slices call them. A deferred check lets a header commit only with its
  draft CONFIRMED by the same approver under financial.approve and at least one effect.
- The 8e-1 refusal (app.refuse_closed_final_settlement_change) and the 8e-2 refusal of a
  Settlement Credit application reversal let a record through only when it is linked to a
  correction of the same Settlement confirmed in the same transaction
  (app.settlement_correction_linked); never a session setting. VOID, Late-payment Decisions and
  Charges and one-time charge records have no link and stay refused.

Additive and relaxing: two new tables, internal functions, and two refusal functions that accept a
linked record they refused before. No correction can be written before the variant writers exist.
"""

from alembic import op
from sqlalchemy import text

revision = "20261101_97"
down_revision = "20261031_96"
branch_labels = None
depends_on = None

INTERNAL = (
    "app.reject_settlement_correction_mutation()",
    "app.validate_settlement_correction()",
    "app.assert_settlement_correction_confirmed()",
    "app.validate_settlement_correction_effect()",
    "app.settlement_correction_id(uuid)",
    "app.settlement_correction_linked(uuid,text,uuid)",
    "app.begin_settlement_correction(uuid,uuid,uuid,text)",
    "app.link_settlement_correction_effect(uuid,text,uuid)",
)
CLOSED_GUARD = "app.refuse_closed_final_settlement_change()"
CREDIT_REVERSAL_GUARD = "app.refuse_final_settlement_credit_application_reversal()"

# One link column per linked table (DB-SETTLE-005 as amended by owner answer 2).
LINKS = (
    ("invoice_id", "app.invoices"),
    ("invoice_adjustment_id", "app.invoice_adjustments"),
    ("invoice_adjustment_reversal_id", "app.invoice_adjustment_reversals"),
    ("payment_allocation_id", "app.payment_allocations"),
    ("payment_allocation_reversal_id", "app.payment_allocation_reversals"),
    ("payment_reversal_id", "app.payment_reversals"),
    ("customer_credit_application_id", "app.customer_credit_applications"),
    ("credit_application_reversal_id", "app.customer_credit_application_reversals"),
    ("customer_credit_reversal_id", "app.customer_credit_reversals"),
    ("deposit_application_id", "app.deposit_applications"),
    ("deposit_disposition_reversal_id", "app.deposit_disposition_reversals"),
    ("deposit_receipt_reversal_id", "app.deposit_receipt_reversals"),
    ("late_payment_charge_correction_id", "app.late_payment_charge_corrections"),
    ("refund_id", "app.refunds"),
    ("refund_correction_id", "app.refund_corrections"),
)

CLOSED_GUARD_REPLACEMENTS = (
    (
        "DECLARE v_invoice uuid; v_lease uuid; v_closed timestamptz;",
        "DECLARE v_invoice uuid; v_lease uuid; v_closed timestamptz; v_settlement uuid; v_record uuid;",
    ),
    (
        "            IF v_invoice IS NOT NULL THEN\n"
        "                SELECT invoice.lease_id INTO v_lease FROM app.invoices invoice WHERE invoice.id=v_invoice;\n"
        "            END IF;\n",
        "            IF v_invoice IS NOT NULL THEN\n"
        "                SELECT invoice.lease_id INTO v_lease FROM app.invoices invoice WHERE invoice.id=v_invoice;\n"
        "            END IF;\n"
        "            -- V1-056 sub-slice 10a: the tables a post-settlement correction may write.\n"
        "            IF TG_TABLE_NAME IN ('invoices','invoice_adjustments','invoice_adjustment_reversals',\n"
        "                'late_payment_charge_corrections') THEN\n"
        "                v_record:=NEW.id;\n"
        "            END IF;\n",
    ),
    (
        "            SELECT settlement.closed_at INTO v_closed FROM app.final_settlements settlement\n"
        "            WHERE settlement.lease_id=v_lease FOR SHARE;\n"
        "            IF v_closed IS NOT NULL THEN\n",
        "            SELECT settlement.closed_at,settlement.id INTO v_closed,v_settlement\n"
        "            FROM app.final_settlements settlement\n"
        "            WHERE settlement.lease_id=v_lease FOR SHARE;\n"
        "            -- BR-SETTLE-013 (sub-slice 10a): a record linked to a correction of this Settlement,\n"
        "            -- confirmed in this same transaction, passes; nothing else does.\n"
        "            IF v_closed IS NOT NULL AND (v_record IS NULL\n"
        "                OR app.settlement_correction_linked(v_settlement,TG_TABLE_NAME,v_record) IS NOT TRUE) THEN\n",
    ),
)

CREDIT_REVERSAL_GUARD_REPLACEMENTS = (
    (
        "            IF EXISTS(SELECT 1 FROM app.customer_credit_applications application\n"
        "                WHERE application.id=NEW.credit_application_id AND application.final_settlement_id IS NOT NULL)\n",
        "            -- BR-SETTLE-013 (sub-slice 10a): the reversal passes only when it is linked to a\n"
        "            -- correction of the application's Settlement confirmed in this same transaction.\n"
        "            IF EXISTS(SELECT 1 FROM app.customer_credit_applications application\n"
        "                WHERE application.id=NEW.credit_application_id AND application.final_settlement_id IS NOT NULL\n"
        "                  AND app.settlement_correction_linked(application.final_settlement_id,\n"
        "                      'customer_credit_application_reversals',NEW.id) IS NOT TRUE)\n",
    ),
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
            raise RuntimeError(f"Settlement correction source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    link_columns = ",\n".join(
        f"            {column} uuid UNIQUE REFERENCES {table}(id) ON DELETE RESTRICT"
        " DEFERRABLE INITIALLY DEFERRED"
        for column, table in LINKS
    )
    link_names = ",".join(column for column, _ in LINKS)
    link_match = "\n                    OR ".join(
        f"(p_table='{table.removeprefix('app.')}' AND effect.{column}=p_record)"
        for column, table in LINKS
    )
    op.execute(f"""
        -- DB-SETTLE-003: the post-settlement correction header. It carries no amount.
        CREATE TABLE app.settlement_corrections (
            id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'),
            final_settlement_id uuid NOT NULL REFERENCES app.final_settlements(id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK (reason=btrim(reason) AND length(reason) BETWEEN 1 AND 1000),
            occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK (authorization_reference='financial.approve'),
            correlation_id uuid NOT NULL UNIQUE REFERENCES app.financial_drafts(id) ON DELETE RESTRICT
        );
        CREATE INDEX settlement_corrections_settlement_idx
            ON app.settlement_corrections(final_settlement_id,occurred_at,id);

        -- DB-SETTLE-005: exactly one typed link per effect row.
        CREATE TABLE app.settlement_correction_effects (
            id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'),
            settlement_correction_id uuid NOT NULL
                REFERENCES app.settlement_corrections(id) ON DELETE RESTRICT,
            effect_sequence smallint NOT NULL CHECK (effect_sequence>0),
{link_columns},
            UNIQUE (settlement_correction_id,effect_sequence),
            CONSTRAINT settlement_correction_effect_one_link CHECK (num_nonnulls({link_names})=1)
        );

        CREATE FUNCTION app.reject_settlement_correction_mutation()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Post-settlement corrections are append-only' USING ERRCODE='55000';
        END $$;
        CREATE TRIGGER settlement_corrections_immutable BEFORE UPDATE OR DELETE
            ON app.settlement_corrections FOR EACH ROW
            EXECUTE FUNCTION app.reject_settlement_correction_mutation();
        CREATE TRIGGER settlement_corrections_no_truncate BEFORE TRUNCATE
            ON app.settlement_corrections FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_settlement_correction_mutation();
        CREATE TRIGGER settlement_correction_effects_immutable BEFORE UPDATE OR DELETE
            ON app.settlement_correction_effects FOR EACH ROW
            EXECUTE FUNCTION app.reject_settlement_correction_mutation();
        CREATE TRIGGER settlement_correction_effects_no_truncate BEFORE TRUNCATE
            ON app.settlement_correction_effects FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_settlement_correction_mutation();

        -- A correction needs its closed Settlement and its SETTLEMENT_CORRECTION draft. The only time
        -- checks are "not before the closure" and "not later than the clock": no time limit.
        CREATE FUNCTION app.validate_settlement_correction()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_settlement app.final_settlements%ROWTYPE;
        BEGIN
            SELECT * INTO v_settlement FROM app.final_settlements WHERE id=NEW.final_settlement_id;
            IF v_settlement.id IS NULL THEN
                RAISE EXCEPTION 'A post-settlement correction needs its closed Final Settlement, its draft and valid chronology'
                    USING ERRCODE='23514'; END IF;
            PERFORM app.assert_active_financial_actor(NEW.actor_id,v_settlement.property_id);
            IF v_settlement.closed_at IS NULL
                OR NEW.occurred_at<v_settlement.closed_at
                OR NEW.occurred_at>clock_timestamp()+interval '5 seconds'
                OR NOT EXISTS(SELECT 1 FROM app.financial_drafts draft
                    WHERE draft.id=NEW.correlation_id AND draft.kind='SETTLEMENT_CORRECTION'
                      AND draft.prepare_capability='final_settlements.prepare'
                      AND draft.property_id=v_settlement.property_id
                      AND draft.payload->>'final_settlement_id'=v_settlement.id::text
                      AND draft.reason=NEW.reason)
            THEN RAISE EXCEPTION 'A post-settlement correction needs its closed Final Settlement, its draft and valid chronology'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER settlement_corrections_validate BEFORE INSERT ON app.settlement_corrections
            FOR EACH ROW EXECUTE FUNCTION app.validate_settlement_correction();

        -- At commit: the draft is CONFIRMED by the correction's approver under financial.approve,
        -- in this same transaction, and the correction has at least one effect.
        CREATE FUNCTION app.assert_settlement_correction_confirmed()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                WHERE decision.draft_id=NEW.correlation_id AND decision.decision='CONFIRMED'
                  AND decision.decided_by=NEW.actor_id
                  AND decision.authorization_reference='financial.approve'
                  AND decision.result->>'transaction_id'=pg_current_xact_id()::text
                  AND decision.decided_at>=transaction_timestamp())
            THEN RAISE EXCEPTION 'A post-settlement correction needs its draft confirmed by its approver'
                USING ERRCODE='42501'; END IF;
            IF NOT EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                WHERE effect.settlement_correction_id=NEW.id)
            THEN RAISE EXCEPTION 'A post-settlement correction needs at least one effect'
                USING ERRCODE='23514'; END IF;
            RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER settlement_corrections_confirmed AFTER INSERT
            ON app.settlement_corrections DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION app.assert_settlement_correction_confirmed();

        -- An effect belongs to a correction confirmed in this same transaction: its draft's
        -- CONFIRMED decision carries this top-level transaction id.
        CREATE FUNCTION app.validate_settlement_correction_effect()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM app.settlement_corrections correction
                WHERE correction.id=NEW.settlement_correction_id
                  AND EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
                      WHERE decision.draft_id=correction.correlation_id AND decision.decision='CONFIRMED'
                        AND decision.result->>'transaction_id'=pg_current_xact_id()::text
                        AND decision.decided_at>=transaction_timestamp()))
            THEN RAISE EXCEPTION 'A correction effect is written with its correction'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER settlement_correction_effects_validate BEFORE INSERT
            ON app.settlement_correction_effects FOR EACH ROW
            EXECUTE FUNCTION app.validate_settlement_correction_effect();

        -- The correction id a draft writes, so each draft corrects at most once.
        CREATE FUNCTION app.settlement_correction_id(p_draft uuid)
        RETURNS uuid LANGUAGE sql IMMUTABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT md5('settlement-correction:' || p_draft::text)::uuid
        $$;

        -- Whether a record is linked to a correction of this Settlement confirmed in this
        -- transaction (never NULL).
        CREATE FUNCTION app.settlement_correction_linked(p_settlement uuid,p_table text,p_record uuid)
        RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT EXISTS(SELECT 1 FROM app.settlement_correction_effects effect
                JOIN app.settlement_corrections correction
                    ON correction.id=effect.settlement_correction_id
                JOIN app.financial_draft_decisions decision
                    ON decision.draft_id=correction.correlation_id AND decision.decision='CONFIRMED'
                WHERE correction.final_settlement_id=p_settlement
                  AND decision.result->>'transaction_id'=pg_current_xact_id()::text
                  AND decision.decided_at>=transaction_timestamp()
                  AND ({link_match}))
        $$;

        -- Internal: confirms a SETTLEMENT_CORRECTION draft and writes its correction header. The
        -- variant writers (later sub-slices) call it first, then link and write each record.
        CREATE FUNCTION app.begin_settlement_correction(p_property uuid,p_approver uuid,p_draft uuid,
            p_authorization text)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_draft app.financial_drafts%ROWTYPE; v_settlement app.final_settlements%ROWTYPE;
            v_correction uuid;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property,p_approver);
            PERFORM app.assert_active_financial_actor(p_approver,p_property);
            IF p_authorization IS DISTINCT FROM 'financial.approve' THEN
                RAISE EXCEPTION 'Only financial.approve may confirm a post-settlement correction'
                    USING ERRCODE='42501'; END IF;
            IF p_draft IS NULL THEN
                RAISE EXCEPTION 'Post-settlement correction input is invalid' USING ERRCODE='22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('financial-draft:' || p_draft::text,0));
            SELECT * INTO v_draft FROM app.financial_drafts WHERE id=p_draft AND property_id=p_property;
            IF NOT FOUND OR v_draft.kind<>'SETTLEMENT_CORRECTION' THEN
                RAISE EXCEPTION 'Post-settlement correction draft was not found' USING ERRCODE='P0002'; END IF;
            IF v_draft.payload->>'final_settlement_id' IS NULL
                OR v_draft.payload->>'final_settlement_id'
                    !~ '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
            THEN RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
            SELECT * INTO v_settlement FROM app.final_settlements
            WHERE id=(v_draft.payload->>'final_settlement_id')::uuid AND property_id=p_property;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Final Settlement was not found' USING ERRCODE='P0002'; END IF;
            -- The Settlement's draft lock first, as the Settlement recorder and confirm take it.
            PERFORM pg_advisory_xact_lock(hashtextextended('final-settlement-draft:' || v_settlement.id::text,0));
            v_draft:=app.lock_pending_financial_draft(p_property,p_draft);
            SELECT * INTO v_settlement FROM app.final_settlements WHERE id=v_settlement.id FOR SHARE;
            IF v_settlement.closed_at IS NULL THEN
                RAISE EXCEPTION 'A post-settlement correction needs a closed Final Settlement'
                    USING ERRCODE='55000'; END IF;
            v_correction:=app.settlement_correction_id(p_draft);
            PERFORM app.confirm_financial_draft_record(p_property,p_approver,p_draft,'SETTLEMENT_CORRECTION',
                jsonb_build_object('settlement_correction_id',v_correction,
                    'final_settlement_id',v_settlement.id,
                    'transaction_id',pg_current_xact_id()::text),'financial.approve');
            INSERT INTO app.settlement_corrections(id,final_settlement_id,reason,occurred_at,actor_id,
                authorization_reference,correlation_id)
            VALUES (v_correction,v_settlement.id,v_draft.reason,clock_timestamp(),p_approver,
                'financial.approve',p_draft);
            RETURN v_correction;
        END $$;

        -- Internal: links one record to the correction, before the writer writes that record.
        CREATE FUNCTION app.link_settlement_correction_effect(p_correction uuid,p_link text,p_record uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_effect uuid:=gen_random_uuid(); v_sequence integer;
        BEGIN
            IF p_correction IS NULL OR p_record IS NULL OR p_link IS NULL
                OR p_link NOT IN ({",".join(f"'{column}'" for column, _ in LINKS)})
            THEN RAISE EXCEPTION 'Post-settlement correction effect is invalid' USING ERRCODE='22023'; END IF;
            SELECT COALESCE(max(effect.effect_sequence),0)+1 INTO v_sequence
            FROM app.settlement_correction_effects effect WHERE effect.settlement_correction_id=p_correction;
            INSERT INTO app.settlement_correction_effects(id,settlement_correction_id,effect_sequence,{
        link_names
    })
            SELECT v_effect,p_correction,v_sequence,{
        ",".join(f"CASE WHEN p_link='{column}' THEN p_record END" for column, _ in LINKS)
    };
            RETURN v_effect;
        END $$;
    """)
    _patch(CLOSED_GUARD, CLOSED_GUARD_REPLACEMENTS)
    _patch(CREDIT_REVERSAL_GUARD, CREDIT_REVERSAL_GUARD_REPLACEMENTS)
    op.execute(
        "REVOKE ALL ON TABLE app.settlement_corrections, app.settlement_correction_effects "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Settlement correction migration is forward-only")
