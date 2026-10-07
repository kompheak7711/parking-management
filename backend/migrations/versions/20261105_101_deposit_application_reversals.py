# ruff: noqa: E501
"""Deposit application reversals (V1-056 sub-slice 10c-2a-1).

BR-SETTLE-013, BR-SETTLE-012, BR-SETTLE-009, BR-LEDGER-003, BR-AUTH-010; DB-DEP-006,
DB-SETTLE-005, DB-DER-004, DB-DER-010; owner answer 2 to Q-2026-10-06-36 and the owner answers to
Q-2026-10-07-41.

- The append-only table app.deposit_application_reversals (DB-DEP-006): a Final Settlement
  Deposit application is reversed only through a post-settlement correction of its Settlement
  confirmed in the same transaction, by that correction's approver under financial.approve, so
  the Deposit holds the amount again and the obligation owes it again. It takes the Deposit and
  target locks and keeps the chronology of the Deposit application, and at commit refreshes the
  Invoice status. No role may read or write the table; the correction writers (sub-slices
  10c-2a-3 and 10e) write it.
- DB-SETTLE-005 gains the link deposit_application_reversal_id; the link functions are rebuilt
  with it (the sub-slice 10b pattern).
- Every reader of Deposit applications counts only applications not reversed: the Invoice line
  value paid by Deposits, the Deposit balance events and snapshot, the Late-payment Charge
  application summary, and the 8a-1 refusal of changes to a Deposit-paid obligation (relaxing:
  an obligation whose Deposit applications are all reversed is no longer refused by it; after
  closure the 8e-1 refusal still stops every change not linked to a correction). The latest
  event time of an allocation target also counts the reversal.
- The Customer Ledger shows each reversal as DEPOSIT_APPLICATION_REVERSED (order 76), the two
  DEPOSIT_APPLIED components with the opposite effect; the ledger page accepts it as a filter.
  The Deposit history reads reversals through the bounded app.deposit_application_reversal_history.

No writer is added: until a correction writer exists no reversal can be written, so every earlier
result is unchanged.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op
from sqlalchemy import text

revision = "20261105_101"
down_revision = "20261104_100"
branch_labels = None
depends_on = None

LEDGER_PAGE = (
    "app.customer_ledger_page(uuid,uuid,uuid,text,integer,timestamptz,timestamptz,text,text,"
    "uuid,timestamptz,text,uuid,text)"
)
HISTORY = "app.deposit_application_reversal_history(uuid,uuid)"
INTERNAL = (
    "app.reject_deposit_application_reversal_mutation()",
    "app.validate_deposit_application_reversal()",
    "app.complete_deposit_application_reversal()",
)

READER_REPLACEMENTS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.invoice_line_deposit_value_at(uuid,timestamptz)",
        (
            (
                "            WHERE application.invoice_line_id=p_line_id AND application.occurred_at<=p_as_of\n",
                "            WHERE application.invoice_line_id=p_line_id AND application.occurred_at<=p_as_of\n"
                "              -- DB-DEP-006 (sub-slice 10c-2a-1): a reversed application no longer pays.\n"
                "              AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal\n"
                "                  WHERE reversal.deposit_application_id=application.id AND reversal.occurred_at<=p_as_of)\n",
            ),
        ),
    ),
    (
        "app.deposit_balance_events(uuid)",
        (
            (
                "            UNION ALL SELECT occurred_at,-amount_usd_cents::numeric FROM app.deposit_applications WHERE deposit_id=p_deposit_id\n",
                "            UNION ALL SELECT occurred_at,-amount_usd_cents::numeric FROM app.deposit_applications WHERE deposit_id=p_deposit_id\n"
                "            -- DB-DEP-006 (sub-slice 10c-2a-1): a reversal gives the amount back to the Deposit.\n"
                "            UNION ALL SELECT reversal.occurred_at,application.amount_usd_cents::numeric\n"
                "                FROM app.deposit_application_reversals reversal JOIN app.deposit_applications application ON application.id=reversal.deposit_application_id\n"
                "                WHERE application.deposit_id=p_deposit_id\n",
            ),
        ),
    ),
    (
        "app.deposit_snapshot(uuid)",
        (
            (
                "                        WHERE application.deposit_id = deposit.id), 0)\n",
                "                        WHERE application.deposit_id = deposit.id\n"
                "                          AND NOT EXISTS (SELECT 1 FROM app.deposit_application_reversals AS reversal\n"
                "                              WHERE reversal.deposit_application_id = application.id)), 0)\n",
            ),
        ),
    ),
    (
        "app.late_payment_charge_application_summary(uuid)",
        (
            (
                "                FROM app.deposit_applications application WHERE application.late_payment_charge_id=p_charge_id\n",
                "                FROM app.deposit_applications application WHERE application.late_payment_charge_id=p_charge_id\n"
                "                    AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal WHERE reversal.deposit_application_id=application.id)\n",
            ),
        ),
    ),
    (
        "app.refuse_deposit_applied_obligation_change()",
        (
            (
                "                    WHERE application.late_payment_charge_id=NEW.late_payment_charge_id)\n",
                "                    WHERE application.late_payment_charge_id=NEW.late_payment_charge_id\n"
                "                      AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal\n"
                "                          WHERE reversal.deposit_application_id=application.id))\n",
            ),
            (
                "                WHERE application.invoice_id=NEW.invoice_id)\n",
                "                WHERE application.invoice_id=NEW.invoice_id\n"
                "                  -- Sub-slice 10c-2a-1: only an application that is not reversed.\n"
                "                  AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal\n"
                "                      WHERE reversal.deposit_application_id=application.id))\n",
            ),
        ),
    ),
    (
        "app.allocation_target_latest_at(text,uuid)",
        (
            (
                "                UNION ALL SELECT occurred_at FROM app.deposit_applications\n"
                "                    WHERE (p_kind='INVOICE' AND invoice_id=p_target_id)\n"
                "                        OR (p_kind='LATE_PAYMENT_CHARGE' AND late_payment_charge_id=p_target_id)\n",
                "                UNION ALL SELECT occurred_at FROM app.deposit_applications\n"
                "                    WHERE (p_kind='INVOICE' AND invoice_id=p_target_id)\n"
                "                        OR (p_kind='LATE_PAYMENT_CHARGE' AND late_payment_charge_id=p_target_id)\n"
                "                UNION ALL SELECT reversal.occurred_at FROM app.deposit_application_reversals reversal\n"
                "                    JOIN app.deposit_applications application ON application.id=reversal.deposit_application_id\n"
                "                    WHERE (p_kind='INVOICE' AND application.invoice_id=p_target_id)\n"
                "                        OR (p_kind='LATE_PAYMENT_CHARGE' AND application.late_payment_charge_id=p_target_id)\n",
            ),
        ),
    ),
    (
        LEDGER_PAGE,
        (
            (
                "'DEPOSIT_APPLIED','REFUND_PAID',",
                "'DEPOSIT_APPLIED','DEPOSIT_APPLICATION_REVERSED','REFUND_PAID',",
            ),
        ),
    ),
)

REVERSAL_SQL = """
    -- DB-DEP-006 (owner answer 2 to Q-2026-10-06-36): the reversal of one Final Settlement Deposit
    -- application, written only by a post-settlement correction of its Settlement.
    CREATE TABLE app.deposit_application_reversals (
        id uuid PRIMARY KEY CHECK (id<>'00000000-0000-0000-0000-000000000000'),
        deposit_application_id uuid NOT NULL UNIQUE
            REFERENCES app.deposit_applications(id) ON DELETE RESTRICT,
        reason text NOT NULL CHECK (reason=btrim(reason) AND length(reason) BETWEEN 1 AND 1000),
        occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
        actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
        authorization_reference text NOT NULL CHECK (authorization_reference='financial.approve')
    );
    COMMENT ON TABLE app.deposit_application_reversals IS
        'Append-only reversal of a Final Settlement Deposit application (DB-DEP-006); written only by a post-settlement correction of its Settlement confirmed in the same transaction';
    CREATE FUNCTION app.reject_deposit_application_reversal_mutation()
    RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    BEGIN
        RAISE EXCEPTION 'Deposit application reversals are append-only' USING ERRCODE='55000';
    END $$;
    CREATE TRIGGER deposit_application_reversals_immutable BEFORE UPDATE OR DELETE
        ON app.deposit_application_reversals FOR EACH ROW
        EXECUTE FUNCTION app.reject_deposit_application_reversal_mutation();
    CREATE TRIGGER deposit_application_reversals_no_truncate BEFORE TRUNCATE
        ON app.deposit_application_reversals FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_deposit_application_reversal_mutation();

    -- BR-SETTLE-013 and BR-AUTH-010: a reversal is linked, before it is written, to a correction
    -- of the application's Settlement confirmed in this transaction (the sub-slice 10a rule), by
    -- that correction's approver. It takes the locks and keeps the chronology of every record that
    -- changes these balances (the Deposit application's own check, migration 86): the Deposit, then
    -- the Invoice or Late-payment Charge; later than the latest event of the target and of the
    -- Deposit, not before the closure or the correction, not later than the clock plus 5 seconds
    -- (no other time limit; review round 1).
    CREATE FUNCTION app.validate_deposit_application_reversal()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_application app.deposit_applications%ROWTYPE; v_closed_at timestamptz; v_approver uuid;
        v_correction_at timestamptz; v_target_at timestamptz;
    BEGIN
        SELECT * INTO v_application FROM app.deposit_applications WHERE id=NEW.deposit_application_id;
        IF NOT FOUND THEN RAISE EXCEPTION 'Deposit application was not found' USING ERRCODE='23503'; END IF;
        IF app.settlement_correction_linked(v_application.final_settlement_id,'deposit_application_reversals',
            NEW.id) IS NOT TRUE
        THEN RAISE EXCEPTION 'A Deposit application is reversed only through a post-settlement correction'
            USING ERRCODE='23514'; END IF;
        PERFORM app.serialize_deposit_state(v_application.deposit_id);
        IF v_application.target_kind='INVOICE_LINE' THEN
            PERFORM app.lock_payment_allocation_target('INVOICE',v_application.invoice_id);
            v_target_at:=app.allocation_target_latest_at('INVOICE',v_application.invoice_id);
        ELSE
            PERFORM app.lock_payment_allocation_target('LATE_PAYMENT_CHARGE',v_application.late_payment_charge_id);
            v_target_at:=app.allocation_target_latest_at('LATE_PAYMENT_CHARGE',v_application.late_payment_charge_id);
        END IF;
        SELECT settlement.closed_at INTO v_closed_at FROM app.final_settlements settlement
        WHERE settlement.id=v_application.final_settlement_id;
        SELECT correction.actor_id,correction.occurred_at INTO v_approver,v_correction_at
        FROM app.settlement_correction_effects effect
        JOIN app.settlement_corrections correction ON correction.id=effect.settlement_correction_id
        WHERE effect.deposit_application_reversal_id=NEW.id;
        IF NEW.actor_id IS DISTINCT FROM v_approver
            OR NEW.authorization_reference IS DISTINCT FROM 'financial.approve'
            OR v_closed_at IS NULL OR NEW.occurred_at IS NULL OR NEW.occurred_at<v_closed_at
            OR NEW.occurred_at<v_correction_at
            OR NEW.occurred_at<v_application.occurred_at
            OR NEW.occurred_at<=COALESCE(v_target_at,'-infinity')
            OR NEW.occurred_at<=COALESCE(app.deposit_balance_latest_at(v_application.deposit_id),'-infinity')
            OR NEW.occurred_at>clock_timestamp()+interval '5 seconds'
        THEN RAISE EXCEPTION 'Deposit application reversal actor, authorization or chronology is invalid'
            USING ERRCODE='23514'; END IF;
        -- As the application's reason (migration 86).
        IF app.lease_notice_text_valid(NEW.reason,1000) IS NOT TRUE THEN
            RAISE EXCEPTION 'Deposit application reversal reason is invalid' USING ERRCODE='22023'; END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER deposit_application_reversals_validate BEFORE INSERT
        ON app.deposit_application_reversals FOR EACH ROW
        EXECUTE FUNCTION app.validate_deposit_application_reversal();

    -- At commit, as the Deposit application's own deferred trigger (migration 86): the reversed
    -- line's Invoice gets its status and version refreshed (review round 1).
    CREATE FUNCTION app.complete_deposit_application_reversal()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE v_invoice uuid;
    BEGIN
        SELECT application.invoice_id INTO v_invoice FROM app.deposit_applications application
        WHERE application.id=NEW.deposit_application_id;
        IF v_invoice IS NOT NULL THEN
            PERFORM app.refresh_allocated_invoice(v_invoice,NEW.actor_id,true);
        END IF;
        RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER deposit_application_reversals_complete AFTER INSERT
        ON app.deposit_application_reversals DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION app.complete_deposit_application_reversal();

    -- The Deposit's own history (BR-SETTLE-009): the reversals of one Deposit's applications of
    -- one Property. The runtime role gets EXECUTE on this function only and no table privilege;
    -- the application checks the Deposit read capability for that Property first.
    CREATE FUNCTION app.deposit_application_reversal_history(p_property uuid,p_deposit uuid)
    RETURNS TABLE(reversal_id uuid,application_id uuid,final_settlement_id uuid,target_kind text,
        target_id uuid,amount_usd_cents bigint,reason text,actor_id uuid,authorization_reference text,
        occurred_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        SELECT reversal.id,application.id,application.final_settlement_id,application.target_kind,
            COALESCE(application.invoice_line_id,application.late_payment_charge_id),
            application.amount_usd_cents,reversal.reason,reversal.actor_id,
            reversal.authorization_reference,reversal.occurred_at
        FROM app.deposit_application_reversals reversal
        JOIN app.deposit_applications application ON application.id=reversal.deposit_application_id
        WHERE application.deposit_id=p_deposit
          AND app.deposit_property_id(application.deposit_id)=p_property
    $$;
"""


def _module(file_name: str, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file_name))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Deposit application reversal source is missing: {file_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reversal_components(ledger: ModuleType) -> list[str]:
    """The two DEPOSIT_APPLIED components of the reversed application, with the opposite effect."""
    source = (
        "app.deposit_application_reversals r "
        "JOIN app.deposit_applications a ON a.id=r.deposit_application_id "
        "JOIN app.deposits d ON d.id=a.deposit_id "
        "LEFT JOIN app.invoices i ON i.id=a.invoice_id "
        "LEFT JOIN app.late_payment_charges c ON c.id=a.late_payment_charge_id "
    )
    obligation_customer = "COALESCE(i.customer_id,c.customer_id)"
    common = dict(
        kind="DEPOSIT_APPLICATION_REVERSED",
        order=76,
        table="deposit_application_reversals",
        identity="r.id",
        instant="r.occurred_at",
        prop="app.deposit_property_id(d.id)",
        invoice="a.invoice_id",
        charge="a.late_payment_charge_id",
        deposit="d.id",
        amount="a.amount_usd_cents",
        effect="a.amount_usd_cents::numeric",
        # The same evidence on both components, so one Customer gets exactly one header.
        audit=(
            "jsonb_build_object('reversal_id',r.id,'application_id',a.id,"
            "'final_settlement_id',a.final_settlement_id,'application_stage',a.application_stage,"
            "'deposit_type',d.deposit_type,'deposit_customer_id',d.customer_id,"
            "'target_kind',a.target_kind,'target_customer_id'," + obligation_customer + ","
            "'reason',r.reason)"
        ),
    )
    return [
        ledger.component(
            customer="d.customer_id",
            source=source,
            bucket=(
                "CASE d.deposit_type WHEN 'SECURITY' THEN 'SECURITY_DEPOSIT' ELSE 'PET_DEPOSIT' END"
            ),
            balance_source="d.id",
            **common,
        ),
        ledger.component(
            customer=obligation_customer,
            source=source + "LEFT JOIN app.invoice_lines l ON l.id=a.invoice_line_id",
            bucket=(
                "CASE WHEN a.invoice_line_id IS NOT NULL THEN 'INVOICE' "
                "ELSE 'LATE_PAYMENT_CHARGE' END"
            ),
            balance_source="COALESCE(a.invoice_line_id,a.late_payment_charge_id)",
            line="a.invoice_line_id",
            category="l.category",
            description="l.description",
            **common,
        ),
    ]


def _ledger_projection() -> str:
    """The revision 88 projection (Deposit applications) plus their reversals."""
    previous = _module("20261023_88_deposit_application_ledger.py", "deposit_application_ledger_88")
    ledger = _module("20260909_48_customer_ledger_projection.py", "customer_ledger_projection_48")
    view = str(previous._ledger_projection())
    prefix = "CREATE OR REPLACE VIEW app.customer_ledger_effects WITH(security_invoker=true) AS "
    if not view.startswith(prefix) or "deposit_application_reversals" in view:
        raise RuntimeError("Customer ledger projection contract changed")
    return view + " UNION ALL " + " UNION ALL ".join(_reversal_components(ledger))


def _link_sql() -> str:
    """DB-SETTLE-005 gains deposit_application_reversal_id; the link functions are rebuilt."""
    links = (
        *_module("20261102_98_settlement_extra_charge.py", "settlement_extra_charge_98").LINKS,
        ("deposit_application_reversal_id", "app.deposit_application_reversals"),
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
        -- Owner answer 2 to Q-2026-10-06-36: the Deposit application reversal of a correction.
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
            raise RuntimeError(f"Deposit application reversal source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute(REVERSAL_SQL)
    op.execute(_link_sql())
    for signature, replacements in READER_REPLACEMENTS:
        _patch(signature, replacements)
    op.execute(_ledger_projection())
    op.execute(
        "REVOKE ALL ON TABLE app.deposit_application_reversals "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for function in (HISTORY, *INTERNAL):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {HISTORY} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("Deposit application reversal migration is forward-only")
