# ruff: noqa: E501
"""A right receipt into a Deposit with a forfeiture ground (V1-056 sub-slice 10e-2c).

BR-SETTLE-013, BR-SETTLE-008, DL-032, BR-DEP-019, BR-DEP-022, BR-DEP-023, BR-DEP-026,
BR-AUTH-010; DB-SETTLE-005, DB-DEP-002, DB-DEP-004; owner answers to Q-2026-10-12-88 (point 1
(b), point 2 (c)):

- Point 1: a right receipt into a Deposit whose termination ground says the Property keeps it, and
  that was never forfeited, is forfeited in the same DEPOSIT_RECEIPT_CORRECTION on that ground, as
  a record linked to the correction (DB-SETTLE-005 `deposit_disposition_id`); staff choose nothing.
- Point 2: a right receipt into such a Deposit whose forfeiture was reversed first (answer (a) to
  Q-2026-10-11-83 point 3) needs the staff's choice in the draft, with a reason: `DL_032` (the
  sub-slice 10e-2b path: the plan applies the money and refunds the rest) or `FORFEIT` (forfeited
  again on the same ground). The financial.approve approver confirms it with the correction.
- The draft shows each forfeiture (the Deposit, the amount, the ground's rule, the reason and the
  basis); the plan leaves forfeited money out; the confirm checks the forfeitures again under the
  locks (P5S02) and writes each after the right receipts and before the shared DL-032 step.
- Only the new receipt's money is forfeited: refused while the Deposit would hold other money or
  has a pay-back count (Q-2026-10-12-93, until the owner answers).

Relaxing changes only: the 10e-2b-1 refusal of a right receipt into a Deposit with a forfeiture
ground is replaced by these rules; DB-SETTLE-005 gains the link (the link functions are rebuilt as
in sub-slice 10e-2b-1); the input accepts the optional choice; the other functions gain their
10e-2c parts by exact-text patches.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from sqlalchemy import text

revision = "20261128_124"
down_revision = "20261127_123"
branch_labels = None
depends_on = None

FUNCTION_SQL = r"""
    -- Sub-slice 10e-2c (owner answers to Q-2026-10-12-88): each right receipt the correction
    -- forfeits, read from the checked targets: a Deposit with a ground never forfeited (point 1,
    -- basis TERMINATION_GROUND, the correction's reason) or one whose forfeiture was reversed and
    -- whose new money staff chose to forfeit again (point 2, basis STAFF_CHOICE, the staff reason).
    CREATE FUNCTION app.settlement_deposit_receipt_forfeitures(p_targets jsonb, p_reason text)
    RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT COALESCE(jsonb_agg(jsonb_build_object('deposit_id',item.target->>'deposit_id',
                'deposit_type',item.target->>'deposit_type',
                'amount_usd_cents',(item.target->>'amount_usd_cents')::bigint,
                'governing_rule',item.target->'path'->>'ground',
                'basis',CASE WHEN item.target->>'outcome' IS NULL THEN 'TERMINATION_GROUND'
                    ELSE 'STAFF_CHOICE' END,
                'reason',COALESCE(item.target->>'outcome_reason',p_reason))
            ORDER BY item.position),'[]'::jsonb)
        FROM jsonb_array_elements(p_targets) WITH ORDINALITY item(target,position)
        WHERE item.target->'path'->>'ground' IS NOT NULL
          AND (item.target->'path'->>'forfeiture'='NONE' OR item.target->>'outcome'='FORFEIT')
    $$;

    -- Sub-slice 10e-2c: the forfeiture of a right receipt's money on the termination's ground,
    -- linked to the correction before it is written and dated after the receipt (the slice 6
    -- writers date a forfeiture at the statement's start, before the correction's records). Only a
    -- forfeiture its correction's DEPOSIT_RECEIPT_CORRECTION draft names, only inside that
    -- correction's confirm (as the receipt writer). Every Lease forfeiture check runs on the
    -- insert: the disposition context (the termination record, the ground's rule, the Deposit
    -- state version), the closed-Settlement link, the held value, the pay-back limit and the
    -- Deposit history. The table requires the authorization reference deposits.dispose, as the
    -- slice 6 draft confirmed by financial.approve writes it. No grant.
    CREATE FUNCTION app.write_correction_deposit_forfeiture(p_property uuid, p_correction uuid,
        p_approver uuid, p_deposit uuid, p_amount bigint, p_reason text, p_at timestamptz)
    RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET "TimeZone"='UTC' AS $$
    DECLARE v_draft uuid; v_lease app.leases%ROWTYPE; v_rule text; v_event uuid; v_at timestamptz;
        v_new uuid; v_key text; v_digest text; v_snapshot jsonb;
    BEGIN
        SELECT draft.id INTO v_draft FROM app.settlement_corrections correction
        JOIN app.financial_drafts draft ON draft.id=correction.correlation_id
        WHERE correction.id=p_correction AND correction.actor_id=p_approver
          AND draft.property_id=p_property AND draft.kind='SETTLEMENT_CORRECTION'
          AND draft.payload->>'variant'='DEPOSIT_RECEIPT_CORRECTION'
          AND EXISTS(SELECT 1 FROM jsonb_array_elements(draft.payload->'deposit_receipt_forfeitures') item
              WHERE item->>'deposit_id'=p_deposit::text
                AND (item->>'amount_usd_cents')::bigint=p_amount AND item->>'reason'=p_reason);
        IF v_draft IS NULL THEN
            RAISE EXCEPTION 'The forfeiture is not one the correction''s draft names'
                USING ERRCODE='55000'; END IF;
        IF NOT EXISTS(SELECT 1 FROM app.financial_draft_decisions decision
            WHERE decision.draft_id=v_draft AND decision.decision='CONFIRMED'
              AND decision.decided_by=p_approver AND decision.authorization_reference='financial.approve'
              AND decision.result->>'transaction_id'=pg_current_xact_id()::text
              AND decision.decided_at>=transaction_timestamp())
        THEN RAISE EXCEPTION 'A forfeiture is written only inside its correction''s confirm'
            USING ERRCODE='55000'; END IF;
        SELECT lease.* INTO STRICT v_lease FROM app.deposits deposit
        JOIN app.leases lease ON lease.id=deposit.lease_id WHERE deposit.id=p_deposit;
        -- The ground and the termination record, read again (each refuses an ambiguous record).
        v_rule:=app.lease_deposit_kept_rule(p_property,p_deposit);
        SELECT event.event_id INTO STRICT v_event FROM app.lease_commands event
        WHERE event.lease_id=v_lease.id AND event.property_id=p_property AND event.action='lease.terminate'
          AND event.occurred_at=v_lease.terminated_at;
        -- Only the new receipt's money: the Deposit holds exactly that beyond its pay-back value.
        IF v_rule IS NULL OR app.deposit_held_value_at(p_deposit,'infinity')
                -app.lease_deposit_payback_value(p_deposit)<>p_amount
        THEN RAISE EXCEPTION 'A forfeiture in a receipt correction takes only the new receipt''s money'
            USING ERRCODE='55000'; END IF;
        v_at:=GREATEST(p_at+interval '1 microsecond',clock_timestamp(),
            COALESCE(app.deposit_balance_latest_at(p_deposit),'-infinity')+interval '1 microsecond');
        v_new:=gen_random_uuid();
        v_key:='settlement-deposit-receipt-forfeiture:' || v_draft::text || ':' || p_deposit::text;
        v_digest:=encode(sha256(convert_to(v_key,'UTF8')),'hex');
        PERFORM app.link_settlement_correction_effect(p_correction,'deposit_disposition_id',v_new);
        SET CONSTRAINTS app.disposition_context_source_fk,app.disposition_context_command_fk DEFERRED;
        INSERT INTO app.lease_deposit_disposition_contexts(disposition_id,property_id,actor_id,
            idempotency_key,request_digest,deposit_id,lease_id,amount_usd_cents,effective_date,reason,
            authorization_reference,termination_event_id,governing_rule,expected_state_version)
        VALUES (v_new,p_property,p_approver,md5(v_key)::uuid,v_digest,p_deposit,v_lease.id,p_amount,
            v_lease.actual_termination_date,p_reason,'deposits.dispose',v_event,v_rule,
            app.deposit_disposition_state_version(p_deposit));
        INSERT INTO app.deposit_dispositions(id,deposit_id,amount_usd_cents,governing_reservation_id,
            source_lifecycle_event_id,governing_lease_id,effective_date,reason,occurred_at,actor_id,
            authorization_reference)
        VALUES (v_new,p_deposit,p_amount,NULL,NULL,v_lease.id,v_lease.actual_termination_date,p_reason,
            v_at,p_approver,'deposits.dispose');
        v_snapshot:=app.deposit_snapshot(p_deposit)||jsonb_build_object('deposit_disposition_id',v_new);
        PERFORM app.record_deposit_audit(v_new,'deposit.disposition.recorded','deposit_disposition',
            v_new,p_deposit,p_reason,'financial.approve',p_approver,p_correction,v_snapshot);
        PERFORM app.record_deposit_command(p_property,p_approver,'deposit.disposition.record',
            md5(v_key)::uuid,v_digest,p_deposit,p_reason,'deposits.dispose',v_snapshot);
        SET CONSTRAINTS app.disposition_context_source_fk,app.disposition_context_command_fk IMMEDIATE;
        RETURN v_at;
    END $$;
"""

INTERNAL = (
    "app.settlement_deposit_receipt_forfeitures(jsonb,text)",
    "app.write_correction_deposit_forfeiture(uuid,uuid,uuid,uuid,bigint,text,"
    "timestamp with time zone)",
)

INPUT = "app.settlement_deposit_receipt_correction_input(jsonb)"
INPUT_REPLACEMENTS = (
    (
        "            IF jsonb_typeof(v_item) IS DISTINCT FROM 'object'\n"
        '                OR (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(v_item) key)\n'
        "                    IS DISTINCT FROM ARRAY['amount_usd_cents','deposit_id']\n",
        "            IF jsonb_typeof(v_item) IS DISTINCT FROM 'object'\n"
        '                OR ((SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(v_item) key)\n'
        "                        IS DISTINCT FROM ARRAY['amount_usd_cents','deposit_id']\n"
        "                    -- Sub-slice 10e-2c (owner answer 2 to Q-2026-10-12-88): the staff's choice\n"
        "                    -- for a Deposit whose forfeiture was reversed, with a reason (both or neither).\n"
        '                    AND (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(v_item) key)\n'
        "                        IS DISTINCT FROM ARRAY['amount_usd_cents','deposit_id','outcome','outcome_reason'])\n"
        "                OR (v_item ? 'outcome' AND (jsonb_typeof(v_item->'outcome') IS DISTINCT FROM 'string'\n"
        "                    OR v_item->>'outcome' NOT IN ('DL_032','FORFEIT')\n"
        "                    OR jsonb_typeof(v_item->'outcome_reason') IS DISTINCT FROM 'string'\n"
        "                    OR app.lease_notice_text_valid(v_item->>'outcome_reason',500) IS NOT TRUE))\n",
    ),
    (
        "            v_receipts:=v_receipts||jsonb_build_array(jsonb_build_object('deposit_id',v_deposit,\n"
        "                'amount_usd_cents',(v_item->>'amount_usd_cents')::bigint));\n",
        "            v_receipts:=v_receipts||jsonb_build_array(jsonb_build_object('deposit_id',v_deposit,\n"
        "                'amount_usd_cents',(v_item->>'amount_usd_cents')::bigint)\n"
        "                ||CASE WHEN v_item ? 'outcome' THEN jsonb_build_object('outcome',v_item->>'outcome',\n"
        "                    'outcome_reason',v_item->>'outcome_reason') ELSE '{}'::jsonb END);\n",
    ),
)

TARGETS = "app.settlement_deposit_receipt_correction_targets(uuid,jsonb,jsonb)"
TARGETS_REPLACEMENTS = (
    (
        "                'deposit_type',deposit.deposit_type,\n",
        "                'deposit_type',deposit.deposit_type,\n"
        "                -- Sub-slice 10e-2c: the staff's choice and the pay-back count (Q-2026-10-12-93).\n"
        "                'outcome',item.value->'outcome','outcome_reason',item.value->'outcome_reason',\n"
        "                'payback_count',CASE WHEN deposit.id IS NOT NULL\n"
        "                    THEN app.lease_deposit_payback_count(deposit.id) END,\n",
    ),
)

ALLOWED = "app.assert_settlement_deposit_receipt_targets_allowed(uuid,jsonb,jsonb)"
ALLOWED_REPLACEMENTS = (
    (
        "        -- Q-2026-10-12-88 (answered 2026-10-12, built in sub-slice 10e-2c): until then a Deposit\n"
        "        -- whose termination ground says the Property keeps it takes no new receipt.\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target\n"
        "            WHERE target->'path'->>'ground' IS NOT NULL)\n"
        "        THEN RAISE EXCEPTION 'A new receipt into a Deposit with a forfeiture ground is not supported yet'\n"
        "            USING ERRCODE='55000'; END IF;\n",
        "        -- Sub-slice 10e-2c (owner answers to Q-2026-10-12-88): a Deposit whose termination ground\n"
        "        -- says the Property keeps it. Never forfeited (point 1 (b)): the same correction forfeits\n"
        "        -- the new money, so staff choose nothing. Its forfeiture reversed first (point 2 (c)):\n"
        "        -- staff choose, with a reason, DL-032 or a forfeiture again. No other Deposit takes a choice.\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target\n"
        "            WHERE target->>'outcome' IS NOT NULL\n"
        "              AND (target->'path'->>'ground' IS NULL\n"
        "                  OR target->'path'->>'forfeiture' IS DISTINCT FROM 'REVERSED'))\n"
        "        THEN RAISE EXCEPTION 'Only a Deposit whose forfeiture was reversed takes a choice of outcome'\n"
        "            USING ERRCODE='55000'; END IF;\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target\n"
        "            WHERE target->>'outcome' IS NULL AND target->'path'->>'ground' IS NOT NULL\n"
        "              AND target->'path'->>'forfeiture'='REVERSED')\n"
        "        THEN RAISE EXCEPTION 'A new receipt into a Deposit whose forfeiture was reversed needs a choice: DL-032 or a forfeiture again'\n"
        "            USING ERRCODE='55000'; END IF;\n"
        "        -- Only the new receipt's money is forfeited: the Deposit holds nothing else after the\n"
        "        -- correction and has no pay-back count (Q-2026-10-12-93; refused until the owner answers).\n"
        "        IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_targets) target\n"
        "            WHERE target->'path'->>'ground' IS NOT NULL\n"
        "              AND (target->'path'->>'forfeiture'='NONE' OR target->>'outcome'='FORFEIT')\n"
        "              AND (COALESCE((target->>'payback_count')::bigint,0)>0\n"
        "                  OR (target->>'deposit_id' IS DISTINCT FROM p_source->'receipt'->>'deposit_id'\n"
        "                      AND COALESCE((target->>'held_usd_cents')::bigint,0)<>0)))\n"
        "        THEN RAISE EXCEPTION 'A forfeiture in a receipt correction takes only the new receipt''s money'\n"
        "            USING ERRCODE='55000'; END IF;\n",
    ),
)

OVERLAY = "app.settlement_deposit_receipt_correction_overlay(jsonb,jsonb)"
OVERLAY_REPLACEMENTS = (
    (
        "                        FROM jsonb_array_elements(p_receipts) item WHERE item->>'deposit_id'=deposit.id),0))\n",
        "                        FROM jsonb_array_elements(p_receipts) item WHERE item->>'deposit_id'=deposit.id\n"
        "                          -- Sub-slice 10e-2c: forfeited money stays out of the plan.\n"
        "                          AND (item->'forfeit') IS DISTINCT FROM 'true'::jsonb),0))\n",
    ),
)

RECORDER = (
    "app.record_settlement_deposit_receipt_correction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
)
RECORDER_REPLACEMENTS = (
    (
        "        v_overlay jsonb; v_result jsonb; v_lines jsonb;\n    BEGIN\n",
        "        v_overlay jsonb; v_result jsonb; v_lines jsonb; v_targets jsonb;\n"
        "        v_forfeitures jsonb:='[]'::jsonb;\n    BEGIN\n",
    ),
    (
        "            PERFORM app.assert_settlement_deposit_receipt_targets_allowed(v_settlement.lease_id,v_source,\n"
        "                app.settlement_deposit_receipt_correction_targets(p_property,v_source,v_input->'receipts'));\n"
        "            v_overlay:=app.settlement_deposit_receipt_correction_overlay(v_source,v_input->'receipts');\n",
        "            v_targets:=app.settlement_deposit_receipt_correction_targets(p_property,v_source,\n"
        "                v_input->'receipts');\n"
        "            PERFORM app.assert_settlement_deposit_receipt_targets_allowed(v_settlement.lease_id,v_source,\n"
        "                v_targets);\n"
        "            -- Sub-slice 10e-2c (owner answers to Q-2026-10-12-88): each right receipt the\n"
        "            -- correction forfeits, shown in the draft; its money stays out of the plan.\n"
        "            v_forfeitures:=app.settlement_deposit_receipt_forfeitures(v_targets,p_reason);\n"
        "            v_overlay:=app.settlement_deposit_receipt_correction_overlay(v_source,\n"
        "                (SELECT jsonb_agg(item.value||jsonb_build_object('forfeit',v_forfeitures\n"
        "                        @> jsonb_build_array(jsonb_build_object('deposit_id',item.value->>'deposit_id')))\n"
        "                    ORDER BY item.position)\n"
        "                FROM jsonb_array_elements(v_input->'receipts') WITH ORDINALITY item(value,position)));\n",
    ),
    (
        "                'plan_overlay',v_overlay,'plan_result',v_result) ELSE '{}'::jsonb END;\n",
        "                'plan_overlay',v_overlay,'plan_result',v_result) ELSE '{}'::jsonb END\n"
        "            ||CASE WHEN v_forfeitures<>'[]'::jsonb\n"
        "                THEN jsonb_build_object('deposit_receipt_forfeitures',v_forfeitures)\n"
        "                ELSE '{}'::jsonb END;\n",
    ),
)

HELPER = "app.post_settlement_deposit_receipt_correction(uuid,uuid,uuid,uuid,uuid,text)"
HELPER_REPLACEMENTS = (
    (
        "        v_key text; v_receipts jsonb; v_item jsonb;\n    BEGIN\n",
        "        v_key text; v_receipts jsonb; v_item jsonb; v_targets jsonb;\n"
        "        v_forfeitures jsonb:='[]'::jsonb;\n    BEGIN\n",
    ),
    (
        "            PERFORM app.assert_settlement_deposit_receipt_targets_allowed(v_lease,v_source,\n"
        "                app.settlement_deposit_receipt_correction_targets(p_property,v_source,v_receipts));\n"
        "        END IF;\n",
        "            v_targets:=app.settlement_deposit_receipt_correction_targets(p_property,v_source,v_receipts);\n"
        "            PERFORM app.assert_settlement_deposit_receipt_targets_allowed(v_lease,v_source,v_targets);\n"
        "            -- Sub-slice 10e-2c: the forfeitures are exactly the ones the draft showed the approver.\n"
        "            v_forfeitures:=app.settlement_deposit_receipt_forfeitures(v_targets,v_reason);\n"
        "            IF v_forfeitures IS DISTINCT FROM COALESCE((SELECT draft.payload->'deposit_receipt_forfeitures'\n"
        "                FROM app.financial_drafts draft WHERE draft.id=p_draft),'[]'::jsonb)\n"
        "            THEN RAISE EXCEPTION 'The post-settlement correction draft is stale; its sources changed'\n"
        "                USING ERRCODE='P5S02'; END IF;\n"
        "        END IF;\n",
    ),
    (
        "            END LOOP;\n"
        "            PERFORM app.post_settlement_correction_plan(p_property,p_approver,p_draft);\n",
        "            END LOOP;\n"
        "            -- Sub-slice 10e-2c (owner answers to Q-2026-10-12-88): each forfeiture of a right\n"
        "            -- receipt's money, linked, after the receipts and before the shared DL-032 step.\n"
        "            FOR v_item IN SELECT forfeiture.value\n"
        "                FROM jsonb_array_elements(v_forfeitures) WITH ORDINALITY forfeiture(value,position)\n"
        "                ORDER BY forfeiture.position\n"
        "            LOOP\n"
        "                v_at:=app.write_correction_deposit_forfeiture(p_property,p_correction,p_approver,\n"
        "                    (v_item->>'deposit_id')::uuid,(v_item->>'amount_usd_cents')::bigint,\n"
        "                    v_item->>'reason',v_at);\n"
        "            END LOOP;\n"
        "            PERFORM app.post_settlement_correction_plan(p_property,p_approver,p_draft);\n",
    ),
)

RESULT = "app.settlement_deposit_receipt_correction_result(uuid)"
RESULT_REPLACEMENTS = (
    (
        "            'refund_ids',COALESCE((SELECT jsonb_agg(refund_id ORDER BY effect_sequence) FROM effects\n",
        "            -- Sub-slice 10e-2c: the forfeitures of right receipts.\n"
        "            'deposit_disposition_ids',COALESCE((SELECT jsonb_agg(deposit_disposition_id\n"
        "                    ORDER BY effect_sequence) FROM effects\n"
        "                WHERE deposit_disposition_id IS NOT NULL),'[]'::jsonb),\n"
        "            'refund_ids',COALESCE((SELECT jsonb_agg(refund_id ORDER BY effect_sequence) FROM effects\n",
    ),
)

PATCHES = (
    (INPUT, INPUT_REPLACEMENTS),
    (TARGETS, TARGETS_REPLACEMENTS),
    (ALLOWED, ALLOWED_REPLACEMENTS),
    (OVERLAY, OVERLAY_REPLACEMENTS),
    (RECORDER, RECORDER_REPLACEMENTS),
    (HELPER, HELPER_REPLACEMENTS),
    (RESULT, RESULT_REPLACEMENTS),
)


def _link_sql() -> str:
    """DB-SETTLE-005 gains deposit_disposition_id; the link functions are rebuilt (as sub-slice
    10e-2b-1 rebuilt them)."""
    links = (
        *_module("20261102_98_settlement_extra_charge.py", "settlement_extra_charge_98").LINKS,
        ("deposit_application_reversal_id", "app.deposit_application_reversals"),
        ("settlement_pet_classification_id", "app.settlement_pet_classifications"),
        ("deposit_receipt_id", "app.deposit_receipts"),
        ("deposit_disposition_id", "app.deposit_dispositions"),
    )
    column, table = links[-1]
    link_names = ",".join(name for name, _ in links)
    link_match = "\n                OR ".join(
        f"(p_table='{linked.removeprefix('app.')}' AND effect.{name}=p_record)"
        for name, linked in links
    )
    link_allowed = ",".join(f"'{name}'" for name, _ in links)
    link_values = ",".join(f"CASE WHEN p_link='{name}' THEN p_record END" for name, _ in links)
    return f"""
        -- Sub-slice 10e-2c: the forfeiture of a right receipt's money a Deposit receipt correction
        -- writes.
        ALTER TABLE app.settlement_correction_effects
            ADD COLUMN {column} uuid UNIQUE REFERENCES {table}(id) ON DELETE RESTRICT
                DEFERRABLE INITIALLY DEFERRED,
            DROP CONSTRAINT settlement_correction_effect_one_link,
            ADD CONSTRAINT settlement_correction_effect_one_link CHECK (num_nonnulls({link_names})=1);

        -- Whether a record is linked to a correction of this Settlement confirmed in this
        -- transaction (never NULL); rebuilt with the new link.
        CREATE OR REPLACE FUNCTION app.settlement_correction_linked(p_settlement uuid,p_table text,
            p_record uuid)
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

        -- Internal: links one record to the correction, before the writer writes that record;
        -- rebuilt with the new link.
        CREATE OR REPLACE FUNCTION app.link_settlement_correction_effect(p_correction uuid,p_link text,
            p_record uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_effect uuid:=gen_random_uuid(); v_sequence integer;
        BEGIN
            IF p_correction IS NULL OR p_record IS NULL OR p_link IS NULL
                OR p_link NOT IN ({link_allowed})
            THEN RAISE EXCEPTION 'Post-settlement correction effect is invalid' USING ERRCODE='22023'; END IF;
            SELECT COALESCE(max(effect.effect_sequence),0)+1 INTO v_sequence
            FROM app.settlement_correction_effects effect WHERE effect.settlement_correction_id=p_correction;
            INSERT INTO app.settlement_correction_effects(id,settlement_correction_id,effect_sequence,{link_names})
            SELECT v_effect,p_correction,v_sequence,{link_values};
            RETURN v_effect;
        END $$;
    """


def _module(file_name: str, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file_name))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Deposit receipt correction source is missing: {file_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
                f"Deposit receipt correction forfeitures contract changed: {signature}"
            )
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(_link_sql())
    op.execute(FUNCTION_SQL)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for function in INTERNAL:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    raise RuntimeError("Deposit receipt correction forfeitures migration is forward-only")
